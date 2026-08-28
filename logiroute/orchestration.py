"""Orchestration layer coordinating Multi-Agent ADK workflow, Model Routing, and Async Execution."""

import asyncio
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import google.adk as adk
from google.adk.runners import InMemoryRunner
from google.genai import types

from logiroute.agent import create_logiroute_agent
from logiroute.config import config
from logiroute.memory.context_manager import context_manager
from logiroute.memory.session_store import SessionState, memory_store
from logiroute.routing.model_router import StrategicModelRouter, model_router
from logiroute.telemetry.tracing import AuditLogger, trace_span
from logiroute.tools import (
    calculate_reroute_options,
    check_route_conditions,
    locate_inventory,
    request_dispatch_approval,
    send_customer_notification,
    track_shipment,
)

_SHIPMENT_PATTERN = re.compile(r"SHP-[A-Z0-9]{6}", re.IGNORECASE)
_SKU_PATTERN = re.compile(r"(?:MED|ELC|PKG)-[A-Z0-9]+-[A-Z0-9]+", re.IGNORECASE)


class LogisticsOrchestrator:
    """Manages multi-agent execution, strategic model routing, session context, and async workflows."""

    def __init__(self, agent: Optional[adk.Agent] = None):
        self.agent = agent or create_logiroute_agent()
        self.runner = InMemoryRunner(agent=self.agent)

    def _has_active_gemini_key(self) -> bool:
        """Check if a functional Gemini API key or Vertex AI credential is set."""
        return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or os.getenv("GOOGLE_GENAI_USE_VERTEXAI"))

    async def process_query_async(
        self,
        query: str,
        session_id: Optional[str] = None,
        user_id: str = "dispatcher_1",
    ) -> Dict[str, Any]:
        """Asynchronously processes a dispatcher inquiry through multi-agent orchestration and model routing.
        
        Args:
            query: Natural language request or command.
            session_id: Optional session identifier for multi-turn context.
            user_id: Dispatcher user identifier.
            
        Returns:
            Dictionary containing structured dispatch results, model tier, tools invoked, and response text.
        """
        sid = session_id or f"sess-{uuid.uuid4().hex[:8]}"
        cid = f"trace-{uuid.uuid4().hex[:12]}"
        
        with trace_span("orchestrator.process_query", {"session_id": sid, "user_id": user_id}, correlation_id=cid):
            # 1. Fetch or initialize persistent async session
            session = await memory_store.get_or_create_session_async(sid, user_id=user_id)
            session.dialogue_turn_count += 1
            
            # Record user turn in message history
            session.messages.append({"role": "user", "content": query})
            await memory_store.add_message_async(sid, "user", query)

            # 2. Extract mentions of shipment or SKU to update short-term context
            shipment_matches = _SHIPMENT_PATTERN.findall(query)
            if shipment_matches:
                session.active_shipment_id = shipment_matches[0].upper()
            
            target_shipment_id = session.active_shipment_id

            # 3. Strategic Model Routing
            routing_decision = model_router.route_query(
                query,
                context_metadata={"active_shipment_id": target_shipment_id},
            )

            tools_called: List[str] = []
            
            # 4. Check if Gemini credentials are present to invoke full LLM runner
            if self._has_active_gemini_key():
                try:
                    response_text = self._run_via_adk_runner(query, session, cid, tools_called)
                    session.messages.append({"role": "assistant", "content": response_text})
                    await memory_store.add_message_async(sid, "assistant", response_text)
                    await memory_store.save_session_async(session)
                    return {
                        "session_id": sid,
                        "correlation_id": cid,
                        "status": "COMPLETED",
                        "mode": "ADK_LLM_MULTI_AGENT_RUNNER",
                        "model_routing": {
                            "tier": routing_decision.tier.value,
                            "model_name": routing_decision.model_name,
                            "rationale": routing_decision.rationale,
                            "complexity_score": routing_decision.complexity_score,
                        },
                        "response": response_text,
                        "tools_invoked": tools_called,
                        "active_shipment_id": session.active_shipment_id,
                    }
                except Exception as exc:
                    AuditLogger.log_event("orchestrator.llm_fallback", {"error": str(exc)}, correlation_id=cid, level="WARNING")

            # 5. Deterministic Multi-Agent Collaborative Reasoning Engine
            result = await self._run_deterministic_pipeline_async(
                query=query,
                shipment_id=target_shipment_id,
                session=session,
                correlation_id=cid,
                routing_decision=routing_decision,
            )
            
            session.messages.append({"role": "assistant", "content": result.get("response", "")})
            await memory_store.add_message_async(sid, "assistant", result.get("response", ""))
            await memory_store.save_session_async(session)
            return result

    def process_query(
        self,
        query: str,
        session_id: Optional[str] = None,
        user_id: str = "dispatcher_1",
    ) -> Dict[str, Any]:
        """Synchronous wrapper around process_query_async."""
        try:
            return asyncio.run(self.process_query_async(query, session_id=session_id, user_id=user_id))
        except RuntimeError:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(lambda: asyncio.run(self.process_query_async(query, session_id=session_id, user_id=user_id)))
                return future.result()

    def _run_via_adk_runner(
        self,
        query: str,
        session: SessionState,
        correlation_id: str,
        tools_record: List[str],
    ) -> str:
        """Executes the query via ADK's native InMemoryRunner."""
        content = types.Content(parts=[types.Part(text=query)])
        output_parts: List[str] = []
        
        for event in self.runner.run(
            user_id=session.user_id,
            session_id=session.session_id,
            new_message=content,
        ):
            if hasattr(event, "content") and event.content and hasattr(event.content, "parts"):
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        output_parts.append(part.text)
                    if hasattr(part, "function_call") and part.function_call:
                        tools_record.append(part.function_call.name)
            elif hasattr(event, "text") and event.text:
                output_parts.append(event.text)
        
        return "\n".join(output_parts) if output_parts else "LogiRoute multi-agent team processed your request."

    async def _run_deterministic_pipeline_async(
        self,
        query: str,
        shipment_id: Optional[str],
        session: SessionState,
        correlation_id: str,
        routing_decision: Any,
    ) -> Dict[str, Any]:
        """Deterministic collaborative workflow executing specialized sub-agent responsibilities."""
        tools_called: List[str] = []
        
        # Scenario A: Inventory Lookup
        sku_matches = _SKU_PATTERN.findall(query)
        if "inventory" in query.lower() or "stock" in query.lower() or sku_matches:
            target_sku = sku_matches[0].upper() if sku_matches else "MED-VAX-882"
            inv_result = locate_inventory(target_sku, required_qty=100, target_location="Atlanta, GA")
            tools_called.append("locate_inventory")
            
            viable = inv_result.total_viable_warehouses
            warehouses = inv_result.warehouses_with_stock
            wh_desc = ", ".join([f"{w.warehouse_name} ({w.available_quantity} units)" for w in warehouses])
            
            response = (
                f"### Inventory Assessment for SKU `{target_sku}`\n"
                f"- **Target Requirement:** 100 units\n"
                f"- **Viable Distribution Centers:** {viable}\n"
                f"- **Stock Breakdown:** {wh_desc}\n"
                f"- **Recommendation:** Inventory located. Recommended dispatch hub is "
                f"`{warehouses[0].warehouse_name if warehouses else 'None'}` for optimal transit."
            )
            return {
                "session_id": session.session_id,
                "correlation_id": correlation_id,
                "status": "COMPLETED",
                "mode": "MULTI_AGENT_DETERMINISTIC_PIPELINE",
                "model_routing": {
                    "tier": routing_decision.tier.value,
                    "model_name": routing_decision.model_name,
                    "rationale": routing_decision.rationale,
                },
                "response": response,
                "tools_invoked": tools_called,
                "active_shipment_id": shipment_id,
                "inventory_summary": inv_result.model_dump(),
            }

        # Scenario B: No shipment ID detected
        if not shipment_id:
            return {
                "session_id": session.session_id,
                "correlation_id": correlation_id,
                "status": "AWAITING_INPUT",
                "mode": "MULTI_AGENT_DETERMINISTIC_PIPELINE",
                "model_routing": {
                    "tier": routing_decision.tier.value,
                    "model_name": routing_decision.model_name,
                    "rationale": routing_decision.rationale,
                },
                "response": (
                    "Please specify a shipment ID (e.g. `SHP-MED001` or `SHP-ELC002`) "
                    "or SKU to investigate logistics status and resolve disruptions."
                ),
                "tools_invoked": [],
                "active_shipment_id": None,
            }

        # Agent 1 (DiagnosticAgent): Track Shipment
        tracking = track_shipment(shipment_id)
        tools_called.append("track_shipment")
        if not tracking.success or not tracking.shipment:
            return {
                "session_id": session.session_id,
                "correlation_id": correlation_id,
                "status": "ERROR",
                "mode": "MULTI_AGENT_DETERMINISTIC_PIPELINE",
                "model_routing": {
                    "tier": routing_decision.tier.value,
                    "model_name": routing_decision.model_name,
                },
                "response": f"Tracking Error: {tracking.error}",
                "tools_invoked": tools_called,
                "active_shipment_id": shipment_id,
            }

        shipment = tracking.shipment
        customer_id = shipment.customer_id
        customer = memory_store.get_customer_profile(customer_id) if customer_id else None
        customer_tier = customer.sla_tier if customer else "STANDARD"
        
        # Check if Cold-Chain violation (P0) or Weather Delay (P1)
        is_cold_chain = shipment.is_cold_chain
        temp = shipment.temperature_celsius
        max_temp = shipment.target_max_temp_celsius
        has_cold_chain_breach = is_cold_chain and temp is not None and max_temp is not None and temp > max_temp
        has_delay = shipment.delay_minutes > 0

        # If on schedule and no temperature breach, provide status report without rerouting
        if not has_delay and not has_cold_chain_breach:
            response_md = (
                f"## LogiRoute Dispatch Status: `{shipment_id}`\n\n"
                f"- **Customer:** {shipment.customer_name} (Tier: `{customer_tier}`)\n"
                f"- **Carrier:** {shipment.carrier} | **Location:** {shipment.current_location}\n"
                f"- **Current Status:** `{shipment.status}` (On Schedule, 0 min delay)\n"
                f"- **Route:** {shipment.origin} to {shipment.destination}\n"
                f"- **Estimated Delivery:** {shipment.estimated_delivery}\n\n"
                f"**Status Notice:** Shipment is proceeding normally. No disruption detected; no reroute necessary."
            )
            return {
                "session_id": session.session_id,
                "correlation_id": correlation_id,
                "status": "COMPLETED",
                "mode": "MULTI_AGENT_DETERMINISTIC_PIPELINE",
                "model_routing": {
                    "tier": routing_decision.tier.value,
                    "model_name": routing_decision.model_name,
                },
                "response": response_md,
                "tools_invoked": tools_called,
                "active_shipment_id": shipment_id,
                "approval_status": "NOT_REQUIRED",
            }

        # Investigate Route Conditions
        route_info = None
        if has_delay:
            route_info = check_route_conditions(shipment.origin, shipment.destination)
            tools_called.append("check_route_conditions")

        issue_type = "COLD_CHAIN_ALERT" if has_cold_chain_breach else "WEATHER_DELAY"
        
        # Query Semantic Vector Memory Store for similar past resolutions
        similar_past = await memory_store.find_similar_past_resolutions_async(
            f"{issue_type} for shipment {shipment_id} delay {shipment.delay_reason}",
            top_k=1,
        )
        historical_note = ""
        if similar_past:
            past_res = similar_past[0]
            historical_note = f" (Past Proven Resolution: {past_res.get('resolution_action')})"

        # Agent 2 (PlannerAgent): Calculate Reroute Options
        reroute_result = calculate_reroute_options(shipment_id, issue_type)
        tools_called.append("calculate_reroute_options")
        
        options = reroute_result.options
        chosen_option = next((opt for opt in options if opt.recommended), options[0] if options else None)
        
        approval_status = "NOT_REQUIRED"
        approval_details = None
        
        # Agent 3 (ComplianceAgent): Budget Verification & HITL Authorization Gate
        if chosen_option:
            cost_delta = chosen_option.cost_delta_usd
            approval_res = request_dispatch_approval(
                shipment_id=shipment_id,
                action_type=chosen_option.mode,
                cost_delta_usd=cost_delta,
                rationale=chosen_option.rationale + historical_note,
                customer_id=customer_id,
            )
            tools_called.append("request_dispatch_approval")
            approval_status = approval_res.status
            approval_details = approval_res
            if approval_status == "PENDING_HUMAN_APPROVAL":
                session.pending_approval = approval_res.model_dump()

        # Customer Notification Dispatch
        notif_msg = (
            f"Update on shipment {shipment_id}: Disruption detected ({shipment.delay_reason}). "
            f"Mitigation plan '{chosen_option.mode if chosen_option else 'STANDARD'}' initiated. "
            f"Status: {approval_status}."
        )
        notif_res = send_customer_notification(
            customer_id=customer_id or "CUST-STD-003",
            shipment_id=shipment_id,
            message=notif_msg,
        )
        tools_called.append("send_customer_notification")

        # Format Structured Response
        response_md = (
            f"## LogiRoute Dispatch Incident Report: `{shipment_id}`\n\n"
            f"- **Customer:** {shipment.customer_name} (Tier: `{customer_tier}`)\n"
            f"- **Carrier:** {shipment.carrier} | **Location:** {shipment.current_location}\n"
            f"- **Current Status:** `{shipment.status}` (Delay: {shipment.delay_minutes} mins)\n"
        )
        
        if is_cold_chain:
            response_md += f"- **Cold-Chain Telemetry:** {temp}°C (Maximum Allowed: {max_temp}°C) ⚠️ **BREACH DETECTED**\n"
            
        if route_info:
            response_md += f"- **Highway & Weather:** {route_info.weather_alert} ({route_info.highway_status})\n"

        if chosen_option:
            response_md += (
                f"\n### Recommended Mitigation Strategy (Planner Specialist)\n"
                f"- **Selected Option:** `{chosen_option.option_id}` ({chosen_option.mode})\n"
                f"- **New Estimated Arrival:** {chosen_option.estimated_arrival}\n"
                f"- **Transit Time Saved:** {chosen_option.transit_hours_saved} hours\n"
                f"- **Financial Impact:** +${chosen_option.cost_delta_usd:.2f} USD\n"
                f"- **Rationale:** {chosen_option.rationale}\n"
            )

        if historical_note:
            response_md += f"- **Vector Memory Match:** Verified against historical resolution pattern `{similar_past[0].get('incident_id')}`\n"

        response_md += (
            f"\n### Guardrails & Dispatch Status (Compliance Specialist)\n"
            f"- **Approval Status:** `{approval_status}`\n"
        )
        
        if approval_status == "PENDING_HUMAN_APPROVAL" and approval_details:
            response_md += f"- **Action Required:** {approval_details.prompt_for_dispatcher}\n"
        elif approval_details:
            response_md += f"- **Ticket ID:** `{approval_details.approval_id}` (Auto-approved under budget)\n"

        response_md += f"- **Customer Notification:** Sent via `{notif_res.channel}` to `{notif_res.destination}`\n"

        return {
            "session_id": session.session_id,
            "correlation_id": correlation_id,
            "status": "COMPLETED",
            "mode": "MULTI_AGENT_DETERMINISTIC_PIPELINE",
            "model_routing": {
                "tier": routing_decision.tier.value,
                "model_name": routing_decision.model_name,
                "complexity_score": routing_decision.complexity_score,
                "rationale": routing_decision.rationale,
            },
            "response": response_md,
            "tools_invoked": tools_called,
            "active_shipment_id": shipment_id,
            "approval_status": approval_status,
            "chosen_option": chosen_option.model_dump() if chosen_option else None,
        }
