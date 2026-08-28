"""Automated Evaluation Suite for LogiRoute Agent Quality and Accuracy.

Measures Intent Accuracy, Tool Selection Precision, Guardrail Compliance, and Latency.
"""

import time
from typing import Any, Dict, List

import pytest
from logiroute.orchestration import LogisticsOrchestrator

EVALUATION_BENCHMARK_CASES = [
    {
        "id": "CASE-01-COLD-CHAIN",
        "query": "Immediate alert: SHP-MED001 temperature is spiking. Investigate and re-route.",
        "expected_tools": ["track_shipment", "calculate_reroute_options", "send_customer_notification"],
        "expected_keywords": ["MED-VAX-882", "AIR", "BREACH"],
        "expected_approval_status": "AUTO_APPROVED",  # $380 is within VIP $500 SLA budget
    },
    {
        "id": "CASE-02-WEATHER-SNOW",
        "query": "Check status of delayed shipment SHP-ELC002 and find alternate route.",
        "expected_tools": ["track_shipment", "check_route_conditions", "calculate_reroute_options"],
        "expected_keywords": ["blizzard", "I-80", "OmniRetail"],
        "expected_approval_status": "AUTO_APPROVED",  # $120 within $200 Enterprise budget
    },
    {
        "id": "CASE-03-INVENTORY-LOCATE",
        "query": "Find warehouse inventory for SKU MED-VAX-882 to replenish stock.",
        "expected_tools": ["locate_inventory"],
        "expected_keywords": ["Inventory Assessment", "Distribution Centers"],
        "expected_approval_status": None,
    },
    {
        "id": "CASE-04-ON-SCHEDULE",
        "query": "Where is shipment SHP-PKG003 right now?",
        "expected_tools": ["track_shipment"],
        "expected_keywords": ["ON_SCHEDULE", "FreightMaster Ground"],
        "expected_approval_status": "NOT_REQUIRED",
    },
]


def test_evaluation_benchmark_suite():
    """Runs automated evaluation suite against defined benchmark test cases."""
    orchestrator = LogisticsOrchestrator()
    
    total_cases = len(EVALUATION_BENCHMARK_CASES)
    passed_tool_precision = 0
    passed_keywords = 0
    passed_guardrails = 0
    total_latency_ms = 0.0

    print("\n--- BEGIN AGENT QUALITY BENCHMARK EVALUATION ---")
    for case in EVALUATION_BENCHMARK_CASES:
        start = time.perf_counter()
        result = orchestrator.process_query(case["query"], session_id=f"eval-{case['id']}")
        duration_ms = (time.perf_counter() - start) * 1000.0
        total_latency_ms += duration_ms

        invoked = result.get("tools_invoked", [])
        response = result.get("response", "")
        
        # Metric 1: Tool Selection Precision
        has_all_tools = all(exp in invoked for exp in case["expected_tools"])
        if has_all_tools:
            passed_tool_precision += 1

        # Metric 2: Keyword / Response Grounding
        has_keywords = any(kw.lower() in response.lower() for kw in case["expected_keywords"])
        if has_keywords:
            passed_keywords += 1

        # Metric 3: Guardrail Compliance
        if case["expected_approval_status"]:
            if result.get("approval_status") == case["expected_approval_status"]:
                passed_guardrails += 1
        else:
            passed_guardrails += 1  # No guardrail expected

    tool_accuracy_pct = (passed_tool_precision / total_cases) * 100.0
    grounding_pct = (passed_keywords / total_cases) * 100.0
    guardrail_compliance_pct = (passed_guardrails / total_cases) * 100.0
    avg_latency_ms = total_latency_ms / total_cases

    print(f"Tool Selection Accuracy:    {tool_accuracy_pct:.1f}% ({passed_tool_precision}/{total_cases})")
    print(f"Response Grounding Rate:    {grounding_pct:.1f}% ({passed_keywords}/{total_cases})")
    print(f"Guardrail Compliance:       {guardrail_compliance_pct:.1f}% ({passed_guardrails}/{total_cases})")
    print(f"Average Execution Latency:  {avg_latency_ms:.2f} ms")
    print("--- END AGENT QUALITY BENCHMARK EVALUATION ---\n")

    # Assert rigorous quality criteria (100% target)
    assert tool_accuracy_pct >= 95.0, "Tool selection accuracy must be >= 95%"
    assert grounding_pct >= 90.0, "Response grounding rate must be >= 90%"
    assert guardrail_compliance_pct == 100.0, "Safety and budget guardrails must be 100% compliant"
    assert avg_latency_ms < 500.0, "Deterministic execution latency must be < 500 ms"
