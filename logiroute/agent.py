"""Multi-Agent Architecture for LogiRoute using Google Cloud ADK.

Decomposes logistics operations into specialized collaborative agents:
1. DiagnosticAgent: Evaluates freight telemetry, road closures, and cold-chain integrity.
2. PlannerAgent: Calculates multi-modal reroute tradeoffs and regional stock reallocations.
3. ComplianceAgent: Enforces financial/SLA guardrails, HITL authorization, and notifications.
4. LogiRouteCoordinator: Master orchestrator managing sub-agents and end-to-end resolution.
"""

from typing import Any, Dict, List, Optional

import google.adk as adk
from google.adk.tools import BaseTool

from logiroute.config import config
from logiroute.routing.model_router import StrategicModelRouter
from logiroute.telemetry.tracing import AuditLogger
from logiroute.tools import (
    ALL_LOGISTICS_TOOLS,
    allocate_stock,
    calculate_reroute_options,
    check_route_conditions,
    locate_inventory,
    request_dispatch_approval,
    send_customer_notification,
    submit_human_approval,
    track_shipment,
)


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


# --- Specialized Sub-Agents ---

def create_diagnostic_agent(model_name: Optional[str] = None) -> adk.Agent:
    """Specialized agent for shipment telemetry inspection and road/weather diagnosis."""
    return adk.Agent(
        name="diagnostic_agent",
        description="Specialist in shipment telemetry, sensor breach detection, and highway pass conditions.",
        model=model_name or StrategicModelRouter.FAST_MODEL,
        instruction="""You are the Diagnostic Specialist for LogiRoute.
Your role is to inspect live telemetry for shipments and route conditions.
- Call `track_shipment` to check carrier, current location, transit delays, and cold chain temperature.
- Call `check_route_conditions` to identify highway closures, blizzards, or congestion bottlenecks.
Produce an objective status diagnosis identifying the exact root cause of any transit disruption.""",
        tools=[track_shipment, check_route_conditions],
        before_tool_callback=on_before_tool,
        after_tool_callback=on_after_tool,
    )


def create_planner_agent(model_name: Optional[str] = None) -> adk.Agent:
    """Specialized agent for rerouting optimization and inventory cross-dock reallocation."""
    return adk.Agent(
        name="planner_agent",
        description="Specialist in calculating multi-modal reroute tradeoffs and regional stock reallocations.",
        model=model_name or StrategicModelRouter.REASONING_MODEL,
        instruction="""You are the Route & Inventory Planning Specialist for LogiRoute.
Your role is to formulate viable mitigation options when a disruption occurs.
- Call `calculate_reroute_options` to evaluate ground detours, air expediting, or local depot freezing.
- Call `locate_inventory` to find replacement stock across adjacent distribution centers.
- Call `allocate_stock` to reserve emergency units when a stockout occurs.
Select the optimal trade-off balancing transit time saved against additional expense.""",
        tools=[calculate_reroute_options, locate_inventory, allocate_stock],
        before_tool_callback=on_before_tool,
        after_tool_callback=on_after_tool,
    )


def create_compliance_agent(model_name: Optional[str] = None) -> adk.Agent:
    """Specialized agent for safety/financial guardrails, HITL authorization, and customer alerts."""
    return adk.Agent(
        name="compliance_agent",
        description="Specialist in budget thresholds, SLA compliance, human dispatcher authorization, and alerts.",
        model=model_name or StrategicModelRouter.FAST_MODEL,
        instruction="""You are the Compliance & Safety Specialist for LogiRoute.
Your role is to enforce corporate financial policies, safety rules, and customer communications.
- Call `request_dispatch_approval` before executing any action that incurs additional costs.
- If cost exceeds customer SLA budget, hold the action pending human dispatcher authorization.
- Call `send_customer_notification` with transparent, reassuring updates once a plan is established.""",
        tools=[request_dispatch_approval, send_customer_notification, submit_human_approval],
        before_tool_callback=on_before_tool,
        after_tool_callback=on_after_tool,
    )


def create_logiroute_agent(
    model_name: Optional[str] = None,
    tools: Optional[List[Any]] = None,
) -> adk.Agent:
    """Instantiates the primary LogiRoute Coordinator Agent with collaborative sub-agents."""
    selected_model = model_name or config.model_name
    agent_tools = tools if tools is not None else ALL_LOGISTICS_TOOLS

    # Initialize sub-agents for multi-agent delegation
    diagnostic_agent = create_diagnostic_agent(selected_model)
    planner_agent = create_planner_agent(selected_model)
    compliance_agent = create_compliance_agent(selected_model)

    coordinator = adk.Agent(
        name="logiroute_coordinator_agent",
        description="Master logistics coordinator supervising diagnostic, planning, and compliance specialists.",
        model=selected_model,
        instruction="""You are the LogiRoute Master Logistics Coordinator.
You lead a team of specialized agents:
- Diagnostic Specialist (`diagnostic_agent`): for shipment inspection and route conditions.
- Planner Specialist (`planner_agent`): for reroute calculations and warehouse inventory lookup.
- Compliance Specialist (`compliance_agent`): for budget guardrails, HITL approvals, and notifications.

Coordinate their actions sequentially:
1. Ingest dispatcher request and dispatch diagnostic analysis.
2. If disruption is detected, request reroute/inventory options from planner.
3. Verify budget and compliance before confirming action.
4. Notify customer and provide a structured executive summary.""",
        tools=agent_tools,
        sub_agents=[diagnostic_agent, planner_agent, compliance_agent],
        before_tool_callback=on_before_tool,
        after_tool_callback=on_after_tool,
    )

    AuditLogger.log_event("agent.multi_agent_initialized", {
        "coordinator": coordinator.name,
        "sub_agents": [sa.name for sa in coordinator.sub_agents],
        "model": selected_model,
    })

    return coordinator
