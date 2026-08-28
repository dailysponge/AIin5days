"""Domain tools package for LogiRoute Agent."""

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

ALL_LOGISTICS_TOOLS = [
    track_shipment,
    check_route_conditions,
    calculate_reroute_options,
    locate_inventory,
    allocate_stock,
    request_dispatch_approval,
    send_customer_notification,
]

__all__ = [
    "ALL_LOGISTICS_TOOLS",
    "allocate_stock",
    "calculate_reroute_options",
    "check_route_conditions",
    "locate_inventory",
    "request_dispatch_approval",
    "send_customer_notification",
    "submit_human_approval",
    "track_shipment",
]
