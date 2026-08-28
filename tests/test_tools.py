"""Unit tests for LogiRoute domain tools."""

import pytest
from logiroute.tools.inventory_tools import allocate_stock, locate_inventory
from logiroute.tools.notification_tools import (
    request_dispatch_approval,
    send_customer_notification,
    submit_human_approval,
)
from logiroute.tools.tracking_tools import (
    calculate_reroute_options,
    check_route_conditions,
    track_shipment,
)


def test_track_shipment_success():
    """Verify tracking lookup for an existing cold-chain medical shipment."""
    res = track_shipment("SHP-MED001")
    assert res["success"] is True
    shipment = res["shipment"]
    assert shipment["shipment_id"] == "SHP-MED001"
    assert shipment["is_cold_chain"] is True
    assert shipment["temperature_celsius"] == 9.4
    assert shipment["carrier"] == "AirFast Global"


def test_track_shipment_invalid_format():
    """Verify input validation rejects malformed shipment IDs."""
    res = track_shipment("INVALID-ID-12345")
    assert res["success"] is False
    assert "Invalid shipment ID format" in res["error"]


def test_track_shipment_not_found():
    """Verify lookup fails gracefully when shipment ID does not exist."""
    res = track_shipment("SHP-999999")
    assert res["success"] is False
    assert "not found" in res["error"]


def test_check_route_conditions_weather_alert():
    """Verify route evaluation flags severe winter conditions on mountain passes."""
    res = check_route_conditions("Seattle, WA", "Denver, CO")
    assert res["highway_status"] == "RESTRICTED"
    assert "Winter Storm" in res["weather_alert"]
    assert res["estimated_delay_minutes"] == 480
    assert "I-80 East" in res["suggested_detour"]


def test_check_route_conditions_normal():
    """Verify route conditions report normal on clear routes."""
    res = check_route_conditions("Dallas, TX", "Austin, TX")
    assert res["highway_status"] == "NORMAL"
    assert res["congestion_level"] == "LOW"


def test_calculate_reroute_options_cold_chain():
    """Verify cold-chain issues trigger emergency air freight recommendation."""
    res = calculate_reroute_options("SHP-MED001", issue_type="COLD_CHAIN_ALERT")
    assert res["success"] is True
    options = res["options"]
    assert len(options) >= 2
    recommended = next(o for o in options if o["recommended"])
    assert recommended["mode"] == "EMERGENCY_AIR_FREIGHT"
    assert recommended["cold_chain_certified"] is True


def test_calculate_reroute_options_weather_ground():
    """Verify standard freight weather delays recommend southern highway detour."""
    res = calculate_reroute_options("SHP-ELC002", issue_type="WEATHER_DELAY")
    assert res["success"] is True
    recommended = next(o for o in res["options"] if o["recommended"])
    assert recommended["mode"] == "GROUND_REROUTE_I80"
    assert recommended["cost_delta_usd"] == 120.00


def test_locate_inventory_available():
    """Verify multi-warehouse stock query finds available distribution centers."""
    res = locate_inventory(sku="MED-VAX-882", required_qty=50, target_location="Atlanta, GA")
    assert res["success"] is True
    assert res["total_viable_warehouses"] > 0
    assert any(w["warehouse_id"] == "DC-EASTCOAST" for w in res["warehouses_with_stock"])


def test_locate_inventory_invalid_qty():
    """Verify negative or zero quantity is rejected."""
    res = locate_inventory(sku="MED-VAX-882", required_qty=-5, target_location="Atlanta, GA")
    assert res["success"] is False
    assert "positive integer" in res["error"]


def test_allocate_stock_lifecycle():
    """Verify inventory reservation and stock depletion."""
    res = allocate_stock(
        sku="PKG-BOX-MED",
        quantity=25,
        source_warehouse_id="DC-SOUTHCENTRAL",
        target_shipment_id="SHP-PKG003",
    )
    assert res["success"] is True
    assert res["allocated_quantity"] == 25
    assert "RESV-DC-SOUTHCENTRAL" in res["reservation_id"]


def test_approval_guardrail_auto_approved():
    """Verify actions under threshold are automatically approved."""
    res = request_dispatch_approval(
        shipment_id="SHP-ELC002",
        action_type="GROUND_REROUTE",
        cost_delta_usd=85.00,
        rationale="Highway detour fuel surcharge",
        customer_id="CUST-ENT-002",  # Threshold is $200.00
    )
    assert res["status"] == "AUTO_APPROVED"
    assert res["approval_id"].startswith("APPR-AUTO-")


def test_approval_guardrail_hitl_triggered():
    """Verify actions exceeding threshold trigger HITL authorization ticket."""
    res = request_dispatch_approval(
        shipment_id="SHP-STD003",
        action_type="AIR_CHARTER",
        cost_delta_usd=750.00,
        rationale="Charter flight for priority shipment",
        customer_id="CUST-STD-003",  # Threshold is $50.00
    )
    assert res["status"] == "PENDING_HUMAN_APPROVAL"
    assert res["approval_id"].startswith("APPR-HITL-")
    assert "ACTION REQUIRED" in res["prompt_for_dispatcher"]


def test_submit_human_approval_flow():
    """Verify dispatcher review submission updates pending ticket."""
    ticket = request_dispatch_approval(
        shipment_id="SHP-STD003",
        action_type="AIR_CHARTER",
        cost_delta_usd=600.00,
        rationale="Emergency flight",
        customer_id="CUST-STD-003",
    )
    appr_id = ticket["approval_id"]
    
    decision = submit_human_approval(
        approval_id=appr_id,
        approved=True,
        reviewer_id="lead_dispatcher_sarah",
        reason="Customer authorized expedite charges via phone.",
    )
    assert decision["success"] is True
    assert decision["ticket"]["status"] == "APPROVED"
    assert decision["ticket"]["reviewed_by"] == "lead_dispatcher_sarah"


def test_send_customer_notification_success():
    """Verify customer notification delivery and channel mapping."""
    res = send_customer_notification(
        customer_id="CUST-VIP-001",
        shipment_id="SHP-MED001",
        message="Vaccine shipment rerouted via air specialty carrier.",
    )
    assert res["success"] is True
    assert res["delivery_status"] == "DELIVERED"
    assert res["channel"] == "EMAIL"
    assert res["destination"] == "critical-ops@apexhealth.com"
