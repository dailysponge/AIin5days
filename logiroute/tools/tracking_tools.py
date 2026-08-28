"""Shipment tracking and route evaluation tools for LogiRoute Agent."""

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from logiroute.telemetry.tracing import AuditLogger, trace_span

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


def track_shipment(shipment_id: str) -> Dict[str, Any]:
    """Retrieves real-time tracking, status, telemetry, and delay information for a shipment.
    
    Args:
        shipment_id: The unique shipment identifier (format: SHP-XXXXXX).
        
    Returns:
        A dictionary containing shipment status, carrier, location, temperature, and items.
    """
    clean_id = shipment_id.strip().upper()
    with trace_span("tool.track_shipment", {"shipment_id": clean_id}):
        if not _SHIPMENT_ID_REGEX.match(clean_id):
            return {
                "success": False,
                "error": f"Invalid shipment ID format '{shipment_id}'. Expected format 'SHP-XXXXXX' (e.g. SHP-MED001).",
            }
        
        shipment = _SHIPMENTS_DB.get(clean_id)
        if not shipment:
            return {
                "success": False,
                "error": f"Shipment '{clean_id}' not found in active tracking registry.",
            }
        
        return {
            "success": True,
            "shipment": shipment,
        }


def check_route_conditions(origin: str, destination: str) -> Dict[str, Any]:
    """Evaluates transit conditions, severe weather alerts, road congestion, and delays between cities.
    
    Args:
        origin: Origin city and state (e.g. 'Seattle, WA').
        destination: Destination city and state (e.g. 'Denver, CO').
        
    Returns:
        Route status, weather alerts, congestion level, and expected transit delay in minutes.
    """
    clean_orig = origin.strip()
    clean_dest = destination.strip()
    with trace_span("tool.check_route_conditions", {"origin": clean_orig, "destination": clean_dest}):
        # Deterministic simulation based on route query
        route_key = f"{clean_orig.lower()}->{clean_dest.lower()}"
        
        if "seattle" in route_key and "denver" in route_key:
            return {
                "route": f"{clean_orig} to {clean_dest}",
                "highway_status": "RESTRICTED",
                "weather_alert": "Winter Storm Warning - Heavy Snowpack & High Winds on I-90 Mountain Pass",
                "congestion_level": "SEVERE",
                "estimated_delay_minutes": 480,
                "suggested_detour": "Reroute via Southern Corridor I-84 to I-80 East",
                "detour_additional_miles": 145,
            }
        elif "boston" in route_key and "atlanta" in route_key:
            return {
                "route": f"{clean_orig} to {clean_dest}",
                "highway_status": "NORMAL",
                "weather_alert": "Clear Conditions",
                "congestion_level": "MODERATE",
                "estimated_delay_minutes": 45,
                "suggested_detour": None,
                "detour_additional_miles": 0,
            }
        else:
            return {
                "route": f"{clean_orig} to {clean_dest}",
                "highway_status": "NORMAL",
                "weather_alert": "No active weather warnings",
                "congestion_level": "LOW",
                "estimated_delay_minutes": 15,
                "suggested_detour": None,
                "detour_additional_miles": 0,
            }


def calculate_reroute_options(shipment_id: str, issue_type: str) -> Dict[str, Any]:
    """Generates structured rerouting strategies, comparing cost delta, transit time, and SLA impact.
    
    Args:
        shipment_id: The identifier of the delayed shipment.
        issue_type: Type of issue ('WEATHER_DELAY', 'COLD_CHAIN_ALERT', 'STOCKOUT').
        
    Returns:
        List of reroute options with cost, time savings, carrier, and recommended option.
    """
    clean_id = shipment_id.strip().upper()
    with trace_span("tool.calculate_reroute_options", {"shipment_id": clean_id, "issue_type": issue_type}):
        tracking = track_shipment(clean_id)
        if not tracking.get("success"):
            return tracking
        
        shipment = tracking["shipment"]
        is_cold_chain = shipment.get("is_cold_chain", False)
        
        options = []
        if is_cold_chain or issue_type == "COLD_CHAIN_ALERT":
            options = [
                {
                    "option_id": "OPT-AIR-EXPRESS",
                    "mode": "EMERGENCY_AIR_FREIGHT",
                    "carrier": "AirFast Global Specialty",
                    "estimated_arrival": (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
                    "transit_hours_saved": 6.0,
                    "cost_delta_usd": 380.00,
                    "cold_chain_certified": True,
                    "requires_approval": True,
                    "recommended": True,
                    "rationale": "Immediate transfer to dry-ice air container preserves vaccine viability within 4-hour window.",
                },
                {
                    "option_id": "OPT-LOCAL-DEPOT",
                    "mode": "LOCAL_COLD_STORAGE_HOLD",
                    "carrier": "Newark ColdHub Facility",
                    "estimated_arrival": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
                    "transit_hours_saved": -16.0,
                    "cost_delta_usd": 90.00,
                    "cold_chain_certified": True,
                    "requires_approval": False,
                    "recommended": False,
                    "rationale": "Safely freezes shipment locally at Newark hub until replacement truck arrives, but misses customer delivery deadline.",
                },
            ]
        else:
            options = [
                {
                    "option_id": "OPT-SOUTH-DETOUR",
                    "mode": "GROUND_REROUTE_I80",
                    "carrier": "SwiftFleet Express",
                    "estimated_arrival": (datetime.now(timezone.utc) + timedelta(hours=20)).isoformat(),
                    "transit_hours_saved": 16.0,
                    "cost_delta_usd": 120.00,
                    "requires_approval": False,
                    "recommended": True,
                    "rationale": "Detours south around mountain blizzard; keeps cargo moving with minimal extra fuel expense.",
                },
                {
                    "option_id": "OPT-AIR-EXPEDITE",
                    "mode": "AIR_EXPEDITED",
                    "carrier": "SkyCargo NextFlight",
                    "estimated_arrival": (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat(),
                    "transit_hours_saved": 30.0,
                    "cost_delta_usd": 450.00,
                    "requires_approval": True,
                    "recommended": False,
                    "rationale": "Fastest transit, but cost exceeds normal enterprise threshold unless customer explicitly authorises.",
                },
            ]
        
        return {
            "success": True,
            "shipment_id": clean_id,
            "options": options,
        }
