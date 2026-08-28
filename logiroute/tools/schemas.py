"""Pydantic schemas for strict validation of all LogiRoute tool inputs and outputs."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class DictAccessibleModel(BaseModel):
    """Base Pydantic model that supports both attribute and dict-style key access."""
    def __getitem__(self, item: str) -> Any:
        try:
            return getattr(self, item)
        except AttributeError:
            raise KeyError(item)

    def get(self, item: str, default: Any = None) -> Any:
        return getattr(self, item, default)

    def __contains__(self, item: str) -> bool:
        return hasattr(self, item)


class IssueType(str, Enum):
    WEATHER_DELAY = "WEATHER_DELAY"
    COLD_CHAIN_ALERT = "COLD_CHAIN_ALERT"
    STOCKOUT = "STOCKOUT"
    ACCIDENT_HOLD = "ACCIDENT_HOLD"
    CUSTOMS_HOLD = "CUSTOMS_HOLD"


class NotificationChannel(str, Enum):
    EMAIL = "EMAIL"
    SMS = "SMS"
    WEBHOOK = "WEBHOOK"


# --- 1. Tracking Schemas ---

class TrackShipmentInput(BaseModel):
    """Input payload for tracking a shipment."""
    shipment_id: str = Field(
        ...,
        description="Unique shipment tracking identifier matching format 'SHP-XXXXXX'",
        pattern=r"^SHP-[A-Z0-9]{6}$",
        examples=["SHP-MED001", "SHP-ELC002"],
    )


class ShipmentItem(DictAccessibleModel):
    sku: str = Field(..., description="Stock Keeping Unit")
    name: str = Field(..., description="Item description")
    quantity: int = Field(..., ge=1, description="Number of units")


class ShipmentDetails(DictAccessibleModel):
    shipment_id: str
    customer_id: str
    customer_name: str
    status: str
    origin: str
    destination: str
    current_location: str
    carrier: str
    is_cold_chain: bool
    temperature_celsius: Optional[float] = None
    target_max_temp_celsius: Optional[float] = None
    estimated_delivery: str
    delay_minutes: int = 0
    delay_reason: Optional[str] = None
    items: List[ShipmentItem] = Field(default_factory=list)


class TrackShipmentOutput(DictAccessibleModel):
    """Output payload returned by shipment tracking."""
    success: bool
    shipment: Optional[ShipmentDetails] = None
    error: Optional[str] = None


# --- 2. Route Condition Schemas ---

class RouteConditionsInput(BaseModel):
    """Input payload for evaluating route conditions between two hubs."""
    origin: str = Field(..., min_length=2, description="Origin city and state", examples=["Seattle, WA"])
    destination: str = Field(..., min_length=2, description="Destination city and state", examples=["Denver, CO"])


class RouteConditionsOutput(DictAccessibleModel):
    """Output payload for route transit and weather conditions."""
    route: str
    highway_status: str
    weather_alert: str
    congestion_level: str
    estimated_delay_minutes: int
    suggested_detour: Optional[str] = None
    detour_additional_miles: int = 0


# --- 3. Reroute Calculation Schemas ---

class CalculateRerouteInput(BaseModel):
    """Input payload for calculating reroute options."""
    shipment_id: str = Field(
        ...,
        description="Shipment ID to calculate rerouting for",
        pattern=r"^SHP-[A-Z0-9]{6}$",
    )
    issue_type: IssueType = Field(
        default=IssueType.WEATHER_DELAY,
        description="Category of transit disruption",
    )


class RerouteOption(DictAccessibleModel):
    option_id: str
    mode: str
    carrier: str
    estimated_arrival: str
    transit_hours_saved: float
    cost_delta_usd: float = Field(..., ge=0.0)
    cold_chain_certified: bool = False
    requires_approval: bool = False
    recommended: bool = False
    rationale: str


class CalculateRerouteOutput(DictAccessibleModel):
    """Output payload of rerouting tradeoffs."""
    success: bool
    shipment_id: str
    options: List[RerouteOption] = Field(default_factory=list)
    error: Optional[str] = None


# --- 4. Inventory Schemas ---

class LocateInventoryInput(BaseModel):
    """Input payload for querying warehouse inventory across the network."""
    sku: str = Field(..., min_length=3, description="SKU identifier to locate", examples=["MED-VAX-882"])
    required_qty: int = Field(..., ge=1, description="Quantity of units needed", examples=[100])
    target_location: str = Field(..., min_length=2, description="Destination city", examples=["Atlanta, GA"])


class WarehouseStockDetail(DictAccessibleModel):
    warehouse_id: str
    warehouse_name: str
    location: str
    available_quantity: int
    satisfies_request: bool


class LocateInventoryOutput(DictAccessibleModel):
    """Output payload with matching distribution centers."""
    success: bool
    sku: str
    required_qty: int
    target_location: str
    warehouses_with_stock: List[WarehouseStockDetail] = Field(default_factory=list)
    total_viable_warehouses: int = 0
    error: Optional[str] = None


class AllocateStockInput(BaseModel):
    """Input payload to reserve inventory for emergency dispatch."""
    sku: str = Field(..., min_length=3)
    quantity: int = Field(..., ge=1)
    source_warehouse_id: str = Field(..., min_length=2)
    target_shipment_id: str = Field(..., pattern=r"^SHP-[A-Z0-9]{6}$")


class AllocateStockOutput(DictAccessibleModel):
    """Output payload confirming stock reservation."""
    success: bool
    reservation_id: Optional[str] = None
    allocated_quantity: Optional[int] = None
    remaining_stock: Optional[int] = None
    warehouse: Optional[str] = None
    error: Optional[str] = None


# --- 5. Approval & HITL Schemas ---

class ApprovalInput(BaseModel):
    """Input payload for requesting dispatch authorization."""
    shipment_id: str = Field(..., pattern=r"^SHP-[A-Z0-9]{6}$")
    action_type: str = Field(..., min_length=2)
    cost_delta_usd: float = Field(..., ge=0.0)
    rationale: str = Field(..., min_length=5)
    customer_id: Optional[str] = None


class ApprovalOutput(DictAccessibleModel):
    """Output payload indicating approval status or pending HITL ticket."""
    status: str  # "AUTO_APPROVED", "PENDING_HUMAN_APPROVAL"
    approval_id: str
    cost_delta_usd: float
    threshold_applied_usd: float
    message: Optional[str] = None
    prompt_for_dispatcher: Optional[str] = None


class HumanApprovalDecisionInput(BaseModel):
    """Input payload for dispatcher decision on a pending HITL ticket."""
    approval_id: str = Field(..., pattern=r"^APPR-(?:AUTO|HITL)-[A-Z0-9]+$")
    approved: bool
    reviewer_id: str = Field(..., min_length=2)
    reason: Optional[str] = Field(default="")


class HumanApprovalDecisionOutput(DictAccessibleModel):
    """Output payload of submitted approval decision."""
    success: bool
    ticket: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


# --- 6. Notification Schemas ---

class NotificationInput(BaseModel):
    """Input payload for customer notification dispatch."""
    customer_id: str = Field(..., min_length=3)
    shipment_id: str = Field(..., pattern=r"^SHP-[A-Z0-9]{6}$")
    message: str = Field(..., min_length=5)
    channel: Optional[NotificationChannel] = None


class NotificationOutput(DictAccessibleModel):
    """Output payload receipt of customer notification dispatch."""
    success: bool
    notification_id: str
    channel: str
    destination: str
    delivery_status: str
    error: Optional[str] = None
