"""Orchestration layer coordinating ADK Agent, Runner, Sessions, and Dispatch Workflow."""

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
from logiroute.memory.session_store import SessionState, memory_store
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
    """Manages agent execution, session context, tool invocation, and dispatch resolution."""

    def __init__(self, agent: Optional[adk.Agent] = None):
        self.agent = agent or create_logiroute_agent()
        self.runner = InMemoryRunner(agent=self.agent)

    def _has_active_gemini_key(self) -> bool:
        """Check if a functional Gemini API key or Vertex AI credential is set."""
        return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or os.getenv("GOOGLE_GENAI_USE_VERTEXAI"))

    def process_query(
        self,
        query: str,
        session_id: Optional[str] = None,
        user_id: str = "dispatcher_1",
    ) -> Dict[str, Any]:
        """Processes a dispatcher inquiry or disruption alert through the ADK workflow.
        
        Args:
            query: Natural language request or command.
            session_id: Optional session identifier for multi-turn context.
            user_id: Dispatcher user identifier.
            
        Returns:
            Dictionary containing structured dispatch results, tools invoked, and response text.
        """
        sid = session_id or f"sess-{uuid.uuid4().hex[:8]}"
        cid = f"trace-{uuid.uuid4().hex[:12]}"
        
        with trace_span("orchestrator.process_query", {"session_id": sid, "user_id": user_id}, correlation_id=cid):
            session = memory_store.get_or_create_session(sid, user_id=user_id)
            session.dialogue_turn_count += 1
            
            # Extract mentions of shipment or SKU to update short-term context
            shipment_matches = _SHIPMENT_PATTERN.findall(query)
            if shipment_matches:
                session.active_shipment_id = shipment_matches[0].upper()
            
            # If active shipment ID wasn't in the query, use the session's active shipment
            target_shipment_id = session.active_shipment_id
            
            tools_called: List[str] = []
            
            # Check if Gemini credentials are present to invoke full LLM runner
            if self._has_active_gemini_key():
                try:
                    response_text = self._run_via_adk_runner(query, session, cid, tools_called)
                    memory_store.save_session(session)
                    return {
                        "session_id": sid,
                        "correlation_id": cid,
                        "status": "COMPLETED",
                        "mode": "ADK_LLM_RUNNER",
                        "response": response_text,
                        "tools_invoked": tools_called,
                        "active_shipment_id": session.active_shipment_id,
                    }
                except Exception as exc:
                    AuditLogger.log_event("orchestrator.llm_fallback", {"error": str(exc)}, correlation_id=cid, level="WARNING")
                    # Gracefully fall back to deterministic workflow engine
            
            # Deterministic ADK-grounded reasoning engine (ensures offline reliability & CI/CD testability)
            result = self._run_deterministic_pipeline(query, target_shipment_id, session, cid)
            memory_store.save_session(session)
            return result

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
        
        return "\n".join(output_parts) if output_parts else "LogiRoute processed your request."

    def _run_deterministic_pipeline(
        self,
        query: str,
        shipment_id: Optional[str],
        session: SessionState,
        correlation_id: str,
    ) -> Dict[str, Any]:
        """Deterministic multi-step dispatch reasoning engine using ADK domain tools."""
        tools_called: List[str] = []
        steps_summary: List[str] = []
        
        # Scenario A: Inventory Lookup
        sku_matches = _SKU_PATTERN.findall(query)
        if "inventory" in query.lower() or "stock" in query.lower() or sku_matches:
            target_sku = sku_matches[0].upper() if sku_matches else "MED-VAX-882"
            inv_result = locate_inventory(target_sku, required_qty=100, target_location="Atlanta, GA")
            tools_called.append("locate_inventory")
            
            viable = inv_result.get("total_viable_warehouses", 0)
            warehouses = inv_result.get("warehouses_with_stock", [])
            wh_desc = ", ".join([f"{w['warehouse_name']} ({w['available_quantity']} units)" for w in warehouses])
            
            response = (
                f"### Inventory Assessment for SKU `{target_sku}`\n"
                f"- **Target Requirement:** 100 units\n"
                f"- **Viable Distribution Centers:** {viable}\n"
                f"- **Stock Breakdown:** {wh_desc}\n"
                f"- **Recommendation:** Inventory located. Recommended dispatch hub is "
                f"`{warehouses[0]['warehouse_name'] if warehouses else 'None'}` for optimal transit."
            )
            return {
                "session_id": session.session_id,
                "correlation_id": correlation_id,
                "status": "COMPLETED",
                "mode": "ADK_DETERMINISTIC_PIPELINE",
                "response": response,
                "tools_invoked": tools_called,
                "active_shipment_id": shipment_id,
                "inventory_summary": inv_result,
            }

        # Scenario B: No shipment ID detected
        if not shipment_id:
            return {
                "session_id": session.session_id,
                "correlation_id": correlation_id,
                "status": "AWAITING_INPUT",
                "mode": "ADK_DETERMINISTIC_PIPELINE",
                "response": (
                    "Please specify a shipment ID (e.g. `SHP-MED001` or `SHP-ELC002`) "
                    "or SKU to investigate logistics status and resolve disruptions."
                ),
                "tools_invoked": [],
                "active_shipment_id": None,
            }

        # Step 1: Track Shipment
        tracking = track_shipment(shipment_id)
        tools_called.append("track_shipment")
        if not tracking.get("success"):
            return {
                "session_id": session.session_id,
                "correlation_id": correlation_id,
                "status": "ERROR",
                "mode": "ADK_DETERMINISTIC_PIPELINE",
                "response": f"Tracking Error: {tracking.get('error')}",
                "tools_invoked": tools_called,
                "active_shipment_id": shipment_id,
            }

        shipment = tracking["shipment"]
        customer_id = shipment.get("customer_id")
        customer = memory_store.get_customer_profile(customer_id) if customer_id else None
        customer_tier = customer.sla_tier if customer else "STANDARD"
        
        # Step 2: Investigate Route Conditions if delay exists
        route_info = None
        if shipment.get("delay_minutes", 0) > 0:
            route_info = check_route_conditions(shipment["origin"], shipment["destination"])
            tools_called.append("check_route_conditions")

        # Step 3: Check if Cold-Chain violation (P0) or Weather Delay (P1)
        is_cold_chain = shipment.get("is_cold_chain", False)
        temp = shipment.get("temperature_celsius")
        max_temp = shipment.get("target_max_temp_celsius")
        has_cold_chain_breach = is_cold_chain and temp and max_temp and temp > max_temp
        has_delay = shipment.get("delay_minutes", 0) > 0

        # If on schedule and no temperature breach, provide status report without rerouting
        if not has_delay and not has_cold_chain_breach:
            response_md = (
                f"## LogiRoute Dispatch Status: `{shipment_id}`\n\n"
                f"- **Customer:** {shipment.get('customer_name')} (Tier: `{customer_tier}`)\n"
                f"- **Carrier:** {shipment.get('carrier')} | **Location:** {shipment.get('current_location')}\n"
                f"- **Current Status:** `{shipment.get('status')}` (On Schedule, 0 min delay)\n"
                f"- **Route:** {shipment.get('origin')} to {shipment.get('destination')}\n"
                f"- **Estimated Delivery:** {shipment.get('estimated_delivery')}\n\n"
                f"**Status Notice:** Shipment is proceeding normally. No disruption detected; no reroute necessary."
            )
            return {
                "session_id": session.session_id,
                "correlation_id": correlation_id,
                "status": "COMPLETED",
                "mode": "ADK_DETERMINISTIC_PIPELINE",
                "response": response_md,
                "tools_invoked": tools_called,
                "active_shipment_id": shipment_id,
                "approval_status": "NOT_REQUIRED",
            }

        issue_type = "COLD_CHAIN_ALERT" if has_cold_chain_breach else "WEATHER_DELAY"
        
        # Step 4: Calculate Reroute Options
        reroute_result = calculate_reroute_options(shipment_id, issue_type)
        tools_called.append("calculate_reroute_options")
        
        options = reroute_result.get("options", [])
        chosen_option = next((opt for opt in options if opt.get("recommended")), options[0] if options else None)
        
        approval_status = "NOT_REQUIRED"
        approval_details = {}
        
        if chosen_option:
            cost_delta = chosen_option.get("cost_delta_usd", 0.0)
            approval_res = request_dispatch_approval(
                shipment_id=shipment_id,
                action_type=chosen_option.get("mode", "REROUTE"),
                cost_delta_usd=cost_delta,
                rationale=chosen_option.get("rationale", "Mitigate in-transit delay"),
                customer_id=customer_id,
            )
            tools_called.append("request_dispatch_approval")
            approval_status = approval_res.get("status", "UNKNOWN")
            approval_details = approval_res
            if approval_status == "PENDING_HUMAN_APPROVAL":
                session.pending_approval = approval_res

        # Step 5: Customer Notification
        notif_msg = (
            f"Update on shipment {shipment_id}: Disruption detected ({shipment.get('delay_reason')}). "
            f"Mitigation plan '{chosen_option.get('mode') if chosen_option else 'STANDARD'}' initiated. "
            f"Status: {approval_status}."
        )
        notif_res = send_customer_notification(
            customer_id=customer_id or "CUST-STD-003",
            shipment_id=shipment_id,
            message=notif_msg,
        )
        tools_called.append("send_customer_notification")

        # Format Response
        response_md = (
            f"## LogiRoute Dispatch Incident Report: `{shipment_id}`\n\n"
            f"- **Customer:** {shipment.get('customer_name')} (Tier: `{customer_tier}`)\n"
            f"- **Carrier:** {shipment.get('carrier')} | **Location:** {shipment.get('current_location')}\n"
            f"- **Current Status:** `{shipment.get('status')}` (Delay: {shipment.get('delay_minutes')} mins)\n"
        )
        
        if is_cold_chain:
            response_md += f"- **Cold-Chain Telemetry:** {temp}°C (Maximum Allowed: {max_temp}°C) ⚠️ **BREACH DETECTED**\n"
            
        if route_info:
            response_md += f"- **Highway & Weather:** {route_info.get('weather_alert')} ({route_info.get('highway_status')})\n"

        if chosen_option:
            response_md += (
                f"\n### Recommended Mitigation Strategy\n"
                f"- **Selected Option:** `{chosen_option.get('option_id')}` ({chosen_option.get('mode')})\n"
                f"- **New Estimated Arrival:** {chosen_option.get('estimated_arrival')}\n"
                f"- **Transit Time Saved:** {chosen_option.get('transit_hours_saved')} hours\n"
                f"- **Financial Impact:** +${chosen_option.get('cost_delta_usd'):.2f} USD\n"
                f"- **Rationale:** {chosen_option.get('rationale')}\n"
            )

        response_md += (
            f"\n### Guardrails & Dispatch Status\n"
            f"- **Approval Status:** `{approval_status}`\n"
        )
        
        if approval_status == "PENDING_HUMAN_APPROVAL":
            response_md += f"- **Action Required:** {approval_details.get('prompt_for_dispatcher')}\n"
        else:
            response_md += f"- **Ticket ID:** `{approval_details.get('approval_id')}` (Auto-approved under budget)\n"

        response_md += f"- **Customer Notification:** Sent via `{notif_res.get('channel')}` to `{notif_res.get('destination')}`\n"

        return {
            "session_id": session.session_id,
            "correlation_id": correlation_id,
            "status": "COMPLETED",
            "mode": "ADK_DETERMINISTIC_PIPELINE",
            "response": response_md,
            "tools_invoked": tools_called,
            "active_shipment_id": shipment_id,
            "approval_status": approval_status,
            "chosen_option": chosen_option,
        }
