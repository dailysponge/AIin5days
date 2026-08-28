"""Shipment tracking and route evaluation tools for LogiRoute Agent using explicit Pydantic schemas."""

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Union

from logiroute.telemetry.tracing import AuditLogger, trace_span
from logiroute.tools.schemas import (
    CalculateRerouteInput,
    CalculateRerouteOutput,
    IssueType,
    RerouteOption,
    RouteConditionsInput,
    RouteConditionsOutput,
    ShipmentDetails,
    ShipmentItem,
    TrackShipmentInput,
    TrackShipmentOutput,
)

# In-memory mock database of active shipments
_SHIPMENTS_DB: Dict[str, Dict[str, Any]] = {
    "SHP-MED001": {
        "shipment_id": "SHP-MED001",
        "customer_id": "CUST-VIP-001",
        "customer_name": "Apex Healthcare Supplies",
        "status": "DELAYED_COLD_CHAIN_ALERT",
        "origin": "Boston, MA",
        "destination": "Atlanta, GA",
        "current_location": "Newark, NJ",
        "carrier": "AirFast Global",
        "is_cold_chain": True,
        "temperature_celsius": 9.4,  # Alert: Max permissible is 4.0 C
        "target_max_temp_celsius": 4.0,
        "estimated_delivery": (datetime.now(timezone.utc) + timedelta(hours=8)).isoformat(),
        "delay_minutes": 180,
        "delay_reason": "Refrigeration compressor malfunction detected at transit hub",
        "items": [{"sku": "MED-VAX-882", "name": "Critical Pediatric Vaccine", "quantity": 400}],
    },
    "SHP-ELC002": {
        "shipment_id": "SHP-ELC002",
        "customer_id": "CUST-ENT-002",
        "customer_name": "OmniRetail Electronics",
        "status": "IN_TRANSIT_WEATHER_HOLD",
        "origin": "Seattle, WA",
        "destination": "Denver, CO",
        "current_location": "Spokane, WA",
        "carrier": "SwiftFleet Express",
        "is_cold_chain": False,
        "temperature_celsius": None,
        "target_max_temp_celsius": None,
        "estimated_delivery": (datetime.now(timezone.utc) + timedelta(hours=36)).isoformat(),
        "delay_minutes": 480,
        "delay_reason": "Severe blizzard closure on I-90 Mountain Pass",
        "items": [{"sku": "ELC-GPU-4090", "name": "AI Accelerator Boards", "quantity": 50}],
    },
    "SHP-PKG003": {
        "shipment_id": "SHP-PKG003",
        "customer_id": "CUST-STD-003",
        "customer_name": "EcoPackaging Direct",
        "status": "ON_SCHEDULE",
        "origin": "Dallas, TX",
        "destination": "Austin, TX",
        "current_location": "Waco, TX",
        "carrier": "FreightMaster Ground",
        "is_cold_chain": False,
        "temperature_celsius": None,
        "target_max_temp_celsius": None,
        "estimated_delivery": (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
        "delay_minutes": 0,
        "delay_reason": None,
        "items": [{"sku": "PKG-BOX-MED", "name": "Corrugated Shipping Cartons", "quantity": 1200}],
    },
}

_SHIPMENT_ID_REGEX = re.compile(r"^SHP-[A-Z0-9]{6}$", re.IGNORECASE)


def track_shipment(shipment_id: Union[str, TrackShipmentInput]) -> TrackShipmentOutput:
    """Retrieves real-time tracking, status, telemetry, and delay information for a shipment.
    
    Args:
        shipment_id: The unique shipment identifier (format: SHP-XXXXXX) or TrackShipmentInput.
        
    Returns:
        TrackShipmentOutput containing shipment status, carrier, location, temperature, and items.
    """
    raw_id = shipment_id.shipment_id if isinstance(shipment_id, TrackShipmentInput) else str(shipment_id)
    clean_id = raw_id.strip().upper()
    
    with trace_span("tool.track_shipment", {"shipment_id": clean_id}):
        if not _SHIPMENT_ID_REGEX.match(clean_id):
            return TrackShipmentOutput(
                success=False,
                error=f"Invalid shipment ID format '{raw_id}'. Expected format 'SHP-XXXXXX' (e.g. SHP-MED001).",
            )
        
        raw_shipment = _SHIPMENTS_DB.get(clean_id)
        if not raw_shipment:
            return TrackShipmentOutput(
                success=False,
                error=f"Shipment '{clean_id}' not found in active tracking registry.",
            )
        
        items = [ShipmentItem(**it) for it in raw_shipment.get("items", [])]
        shipment_details = ShipmentDetails(
            shipment_id=raw_shipment["shipment_id"],
            customer_id=raw_shipment["customer_id"],
            customer_name=raw_shipment["customer_name"],
            status=raw_shipment["status"],
            origin=raw_shipment["origin"],
            destination=raw_shipment["destination"],
            current_location=raw_shipment["current_location"],
            carrier=raw_shipment["carrier"],
            is_cold_chain=raw_shipment["is_cold_chain"],
            temperature_celsius=raw_shipment.get("temperature_celsius"),
            target_max_temp_celsius=raw_shipment.get("target_max_temp_celsius"),
            estimated_delivery=raw_shipment["estimated_delivery"],
            delay_minutes=raw_shipment.get("delay_minutes", 0),
            delay_reason=raw_shipment.get("delay_reason"),
            items=items,
        )
        return TrackShipmentOutput(
            success=True,
            shipment=shipment_details,
        )


def check_route_conditions(
    origin: Union[str, RouteConditionsInput],
    destination: Optional[str] = None,
) -> RouteConditionsOutput:
    """Evaluates transit conditions, severe weather alerts, road congestion, and delays between cities.
    
    Args:
        origin: Origin city/state or RouteConditionsInput.
        destination: Destination city/state.
        
    Returns:
        RouteConditionsOutput with route status, weather alerts, congestion level, and expected delay.
    """
    if isinstance(origin, RouteConditionsInput):
        clean_orig = origin.origin.strip()
        clean_dest = origin.destination.strip()
    else:
        clean_orig = str(origin).strip()
        clean_dest = str(destination or "").strip()

    with trace_span("tool.check_route_conditions", {"origin": clean_orig, "destination": clean_dest}):
        route_key = f"{clean_orig.lower()}->{clean_dest.lower()}"
        
        if "seattle" in route_key and "denver" in route_key:
            return RouteConditionsOutput(
                route=f"{clean_orig} to {clean_dest}",
                highway_status="RESTRICTED",
                weather_alert="Winter Storm Warning - Heavy Snowpack & High Winds on I-90 Mountain Pass",
                congestion_level="SEVERE",
                estimated_delay_minutes=480,
                suggested_detour="Reroute via Southern Corridor I-84 to I-80 East",
                detour_additional_miles=145,
            )
        elif "boston" in route_key and "atlanta" in route_key:
            return RouteConditionsOutput(
                route=f"{clean_orig} to {clean_dest}",
                highway_status="NORMAL",
                weather_alert="Clear Conditions",
                congestion_level="MODERATE",
                estimated_delay_minutes=45,
                suggested_detour=None,
                detour_additional_miles=0,
            )
        else:
            return RouteConditionsOutput(
                route=f"{clean_orig} to {clean_dest}",
                highway_status="NORMAL",
                weather_alert="No active weather warnings",
                congestion_level="LOW",
                estimated_delay_minutes=15,
                suggested_detour=None,
                detour_additional_miles=0,
            )


def calculate_reroute_options(
    shipment_id: Union[str, CalculateRerouteInput],
    issue_type: Union[str, IssueType] = IssueType.WEATHER_DELAY,
) -> CalculateRerouteOutput:
    """Generates structured rerouting strategies, comparing cost delta, transit time, and SLA impact.
    
    Args:
        shipment_id: Identifier of the delayed shipment or CalculateRerouteInput.
        issue_type: Type of issue ('WEATHER_DELAY', 'COLD_CHAIN_ALERT', 'STOCKOUT').
        
    Returns:
        CalculateRerouteOutput with list of reroute options with cost, time savings, and recommendations.
    """
    if isinstance(shipment_id, CalculateRerouteInput):
        clean_id = shipment_id.shipment_id.strip().upper()
        clean_issue = shipment_id.issue_type.value if hasattr(shipment_id.issue_type, "value") else str(shipment_id.issue_type)
    else:
        clean_id = str(shipment_id).strip().upper()
        clean_issue = issue_type.value if hasattr(issue_type, "value") else str(issue_type)

    with trace_span("tool.calculate_reroute_options", {"shipment_id": clean_id, "issue_type": clean_issue}):
        tracking = track_shipment(clean_id)
        if not tracking.success or not tracking.shipment:
            return CalculateRerouteOutput(
                success=False,
                shipment_id=clean_id,
                error=tracking.error or f"Shipment '{clean_id}' could not be located for reroute analysis.",
            )
        
        shipment = tracking.shipment
        is_cold_chain = shipment.is_cold_chain
        
        options: List[RerouteOption] = []
        if is_cold_chain or clean_issue == "COLD_CHAIN_ALERT":
            options = [
                RerouteOption(
                    option_id="OPT-AIR-EXPRESS",
                    mode="EMERGENCY_AIR_FREIGHT",
                    carrier="AirFast Global Specialty",
                    estimated_arrival=(datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
                    transit_hours_saved=6.0,
                    cost_delta_usd=380.00,
                    cold_chain_certified=True,
                    requires_approval=True,
                    recommended=True,
                    rationale="Immediate transfer to dry-ice air container preserves vaccine viability within 4-hour window.",
                ),
                RerouteOption(
                    option_id="OPT-LOCAL-DEPOT",
                    mode="LOCAL_COLD_STORAGE_HOLD",
                    carrier="Newark ColdHub Facility",
                    estimated_arrival=(datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
                    transit_hours_saved=-16.0,
                    cost_delta_usd=90.00,
                    cold_chain_certified=True,
                    requires_approval=False,
                    recommended=False,
                    rationale="Safely freezes shipment locally at Newark hub until replacement truck arrives, but misses customer delivery deadline.",
                ),
            ]
        else:
            options = [
                RerouteOption(
                    option_id="OPT-SOUTH-DETOUR",
                    mode="GROUND_REROUTE_I80",
                    carrier="SwiftFleet Express",
                    estimated_arrival=(datetime.now(timezone.utc) + timedelta(hours=20)).isoformat(),
                    transit_hours_saved=16.0,
                    cost_delta_usd=120.00,
                    cold_chain_certified=False,
                    requires_approval=False,
                    recommended=True,
                    rationale="Detours south around mountain blizzard; keeps cargo moving with minimal extra fuel expense.",
                ),
                RerouteOption(
                    option_id="OPT-AIR-EXPEDITE",
                    mode="AIR_EXPEDITED",
                    carrier="SkyCargo NextFlight",
                    estimated_arrival=(datetime.now(timezone.utc) + timedelta(hours=6)).isoformat(),
                    transit_hours_saved=30.0,
                    cost_delta_usd=450.00,
                    cold_chain_certified=False,
                    requires_approval=True,
                    recommended=False,
                    rationale="Fastest transit, but cost exceeds normal enterprise threshold unless customer explicitly authorizes.",
                ),
            ]
        
        return CalculateRerouteOutput(
            success=True,
            shipment_id=clean_id,
            options=options,
        )
