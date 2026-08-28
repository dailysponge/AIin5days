"""Tests for Multi-Agent Orchestration, Collaborative Logic, and Model Routing."""

import pytest
from logiroute.agent import create_logiroute_agent
from logiroute.orchestration import LogisticsOrchestrator
from logiroute.routing.model_router import ModelTier, model_router


def test_multi_agent_initialization():
    """Verify ADK Multi-Agent Coordinator is configured with specialized collaborative sub-agents."""
    agent = create_logiroute_agent()
    assert agent.name == "logiroute_coordinator_agent"
    assert len(agent.tools) >= 5
    assert len(agent.sub_agents) == 3
    
    sub_agent_names = [sa.name for sa in agent.sub_agents]
    assert "diagnostic_agent" in sub_agent_names
    assert "planner_agent" in sub_agent_names
    assert "compliance_agent" in sub_agent_names


def test_strategic_model_routing():
    """Verify dynamic model routing classifies query complexity correctly."""
    # Routine query -> Fast Tier
    routine_decision = model_router.route_query("Where is shipment SHP-PKG003?")
    assert routine_decision.tier == ModelTier.FAST_TIER
    assert "gemini-2.5-flash" in routine_decision.model_name

    # Emergency / complex reroute query -> Reasoning Tier
    critical_decision = model_router.route_query("Critical cold chain emergency: temperature spiking on vaccine SHP-MED001. Optimize reroute tradeoff.")
    assert critical_decision.tier == ModelTier.REASONING_TIER
    assert "gemini-2.5-pro" in critical_decision.model_name


def test_orchestration_cold_chain_incident():
    """Verify end-to-end diagnosis and mitigation for cold-chain vaccine breach."""
    orchestrator = LogisticsOrchestrator()
    query = "Critical alert on SHP-MED001. Check temperature readings and initiate reroute."
    result = orchestrator.process_query(query, session_id="test-coldchain-sess")
    
    assert result["status"] == "COMPLETED"
    assert result["active_shipment_id"] == "SHP-MED001"
    assert "track_shipment" in result["tools_invoked"]
    assert "calculate_reroute_options" in result["tools_invoked"]
    assert "send_customer_notification" in result["tools_invoked"]
    assert "EMERGENCY_AIR_FREIGHT" in result["response"] or "OPT-AIR-EXPRESS" in result["response"]
    assert result["model_routing"]["tier"] == ModelTier.REASONING_TIER.value


def test_orchestration_weather_delay():
    """Verify weather delay analysis and highway detour selection."""
    orchestrator = LogisticsOrchestrator()
    query = "Investigate weather delays on shipment SHP-ELC002."
    result = orchestrator.process_query(query, session_id="test-weather-sess")
    
    assert result["status"] == "COMPLETED"
    assert result["active_shipment_id"] == "SHP-ELC002"
    assert "check_route_conditions" in result["tools_invoked"]
    assert "GROUND_REROUTE_I80" in result["response"] or "OPT-SOUTH-DETOUR" in result["response"]


def test_orchestration_multi_turn_context():
    """Verify multi-turn session preserves active shipment across turns."""
    orchestrator = LogisticsOrchestrator()
    session_id = "test-multi-turn-sess"
    
    # Turn 1: Introduce shipment
    res1 = orchestrator.process_query("Check on shipment SHP-ELC002", session_id=session_id)
    assert res1["active_shipment_id"] == "SHP-ELC002"
    
    # Turn 2: Follow-up query without re-stating shipment ID
    res2 = orchestrator.process_query("What is the mitigation plan and status?", session_id=session_id)
    assert res2["active_shipment_id"] == "SHP-ELC002"
    assert "SHP-ELC002" in res2["response"]


def test_orchestration_inventory_query():
    """Verify routing of inventory shortage and warehouse lookup queries."""
    orchestrator = LogisticsOrchestrator()
    query = "Check available stock for SKU ELC-GPU-4090 across our warehouses."
    result = orchestrator.process_query(query, session_id="test-inv-sess")
    
    assert result["status"] == "COMPLETED"
    assert "locate_inventory" in result["tools_invoked"]
    assert "Inventory Assessment" in result["response"]


def test_orchestration_missing_id_prompt():
    """Verify agent prompts user when no shipment ID or SKU is found."""
    orchestrator = LogisticsOrchestrator()
    query = "Hello, can you help me with a shipment?"
    result = orchestrator.process_query(query, session_id="test-missing-id-sess")
    
    assert result["status"] == "AWAITING_INPUT"
    assert "Please specify a shipment ID" in result["response"]


@pytest.mark.asyncio
async def test_async_orchestration_pipeline():
    """Verify fully asynchronous execution of the orchestrator pipeline."""
    orchestrator = LogisticsOrchestrator()
    query = "Where is shipment SHP-PKG003 right now?"
    result = await orchestrator.process_query_async(query, session_id="async-eval-sess")
    
    assert result["status"] == "COMPLETED"
    assert result["active_shipment_id"] == "SHP-PKG003"
    assert "ON_SCHEDULE" in result["response"]
