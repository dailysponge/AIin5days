"""Core ADK Agent definition for LogiRoute Logistics Dispatch System."""

from typing import Any, Dict, List, Optional

import google.adk as adk
from google.adk.tools import BaseTool

from logiroute.config import config
from logiroute.telemetry.tracing import AuditLogger, trace_span
from logiroute.tools import ALL_LOGISTICS_TOOLS

AGENT_INSTRUCTIONS = """You are LogiRoute, an autonomous AI Logistics Dispatch and Disruption Resolution Agent.
Your role is to monitor freight shipments, diagnose in-transit disruptions, formulate optimal rerouting or inventory-reallocation strategies, enforce financial/SLA guardrails, and execute customer notifications.

Follow this standard operating procedure (SOP) strictly:
1. IDENTIFY:
   - Extract shipment identifiers (format: SHP-XXXXXX, e.g. SHP-MED001) or inventory SKUs from dispatcher requests.
   - If the user provides a partial or malformed ID, guide them to the correct format.

2. INVESTIGATE:
   - Always call `track_shipment(shipment_id)` first to inspect live location, status, delay causes, and cold-chain sensor readings.
   - If severe weather or road blockages are noted, call `check_route_conditions(origin, destination)` to assess highway pass viability.

3. DIAGNOSE & SOLVE:
   - P0 Critical (Cold Chain Alert): If `is_cold_chain` is True and temperature exceeds maximum allowable threshold, prioritize emergency air freight or local depot cold storage immediately.
   - P1 Disruption (Weather/Accident Delay): Call `calculate_reroute_options(shipment_id, issue_type)` to evaluate alternative ground or air routes.
   - Inventory Stockout: Call `locate_inventory(sku, required_qty, target_location)` to check adjacent distribution centers.

4. SAFETY & GUARDRAILS:
   - Whenever an action incurs extra financial cost, call `request_dispatch_approval(shipment_id, action_type, cost_delta_usd, rationale, customer_id)`.
   - If the cost exceeds allowable threshold ($150.00 or customer SLA limit), report that human dispatcher sign-off is pending with ticket details.
   - Never promise unauthorized bypass of safety or hazardous material protocols.

5. NOTIFY & REPORT:
   - Call `send_customer_notification(customer_id, shipment_id, message, channel)` to keep stakeholders informed with transparent, reassuring updates.
   - Format final dispatch responses with structured markdown, including:
     * Shipment ID & Customer SLA Tier
     * Root Cause Analysis (RCA)
     * Selected Mitigation Strategy
     * ETA Impact & Cost Delta
     * Notification Dispatch Status
"""


def on_before_tool(tool: BaseTool, args: Dict[str, Any], tool_context: Any = None) -> Optional[Dict[str, Any]]:
    """ADK callback executed before any tool runs."""
    tool_name = getattr(tool, "name", str(tool))
    AuditLogger.log_event("agent.before_tool", {"tool": tool_name, "args": args})
    return None


def on_after_tool(tool: BaseTool, args: Dict[str, Any], result: Any, tool_context: Any = None) -> Optional[Any]:
    """ADK callback executed after a tool completes."""
    tool_name = getattr(tool, "name", str(tool))
    AuditLogger.log_event("agent.after_tool", {"tool": tool_name, "success": True})
    return None


def create_logiroute_agent(
    model_name: Optional[str] = None,
    tools: Optional[List[Any]] = None,
) -> adk.Agent:
    """Instantiates and configures the LogiRoute ADK Agent with tools and callbacks.
    
    Args:
        model_name: Optional model override (defaults to config.model_name).
        tools: Optional tool list override (defaults to ALL_LOGISTICS_TOOLS).
        
    Returns:
        Configured google.adk.Agent instance.
    """
    selected_model = model_name or config.model_name
    agent_tools = tools if tools is not None else ALL_LOGISTICS_TOOLS

    agent = adk.Agent(
        name="logiroute_dispatch_agent",
        description="Autonomous AI logistics dispatcher for disruption diagnosis, rerouting, and SLA protection.",
        model=selected_model,
        instruction=AGENT_INSTRUCTIONS,
        tools=agent_tools,
        before_tool_callback=on_before_tool,
        after_tool_callback=on_after_tool,
    )
    
    AuditLogger.log_event("agent.initialized", {
        "agent_name": agent.name,
        "model": selected_model,
        "tool_count": len(agent.tools),
    })
    
    return agent
