"""Tests for Agent Orchestration & Logic."""

import pytest
from logiroute.agent import create_logiroute_agent
from logiroute.orchestration import LogisticsOrchestrator


def test_agent_initialization():
    """Verify ADK Agent is configured with correct instructions, tools, and callbacks."""
    agent = create_logiroute_agent()
    assert agent.name == "logiroute_dispatch_agent"
    assert len(agent.tools) >= 5
    assert agent.before_tool_callback is not None
    assert agent.after_tool_callback is not None


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
