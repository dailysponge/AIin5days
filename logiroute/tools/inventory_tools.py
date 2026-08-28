"""Inventory and warehouse distribution tools for LogiRoute Agent."""

import threading
from typing import Any, Dict, List, Optional

from logiroute.telemetry.tracing import AuditLogger, trace_span

# In-memory mock warehouse inventory
_INVENTORY_LOCK = threading.Lock()
_WAREHOUSE_STOCK: Dict[str, Dict[str, Any]] = {
    "DC-MIDWEST": {
        "warehouse_id": "DC-MIDWEST",
        "name": "Chicago Logistics Hub",
        "location": "Chicago, IL",
        "stock": {
            "MED-VAX-882": 0,  # Depleted
            "ELC-GPU-4090": 20,
            "PKG-BOX-MED": 5000,
        },
    },
    "DC-EASTCOAST": {
        "warehouse_id": "DC-EASTCOAST",
        "name": "New Jersey Supercenter",
        "location": "Newark, NJ",
        "stock": {
            "MED-VAX-882": 650,  # Available
            "ELC-GPU-4090": 100,
            "PKG-BOX-MED": 12000,
        },
    },
    "DC-WESTCOAST": {
        "warehouse_id": "DC-WESTCOAST",
        "name": "Pacific Gateway Center",
        "location": "Seattle, WA",
        "stock": {
            "MED-VAX-882": 150,
            "ELC-GPU-4090": 45,
            "PKG-BOX-MED": 8000,
        },
    },
    "DC-SOUTHCENTRAL": {
        "warehouse_id": "DC-SOUTHCENTRAL",
        "name": "Dallas Freight Crossdock",
        "location": "Dallas, TX",
        "stock": {
            "MED-VAX-882": 300,
            "ELC-GPU-4090": 80,
            "PKG-BOX-MED": 15000,
        },
    },
}


def locate_inventory(sku: str, required_qty: int, target_location: str) -> Dict[str, Any]:
    """Queries distribution centers across the network to locate available stock.
    
    Args:
        sku: Stock Keeping Unit identifier (e.g. 'MED-VAX-882').
        required_qty: Quantity needed to satisfy demand.
        target_location: Target city/destination for delivery.
        
    Returns:
        List of warehouses with available stock, distance estimate, and fulfillment viability.
    """
    clean_sku = sku.strip().upper()
    with trace_span("tool.locate_inventory", {"sku": clean_sku, "required_qty": required_qty, "target_location": target_location}):
        if required_qty <= 0:
            return {
                "success": False,
                "error": f"Required quantity must be a positive integer, got {required_qty}.",
            }
        
        matches: List[Dict[str, Any]] = []
        with _INVENTORY_LOCK:
            for wh_id, wh in _WAREHOUSE_STOCK.items():
                qty = wh["stock"].get(clean_sku, 0)
                if qty >= required_qty:
                    matches.append({
                        "warehouse_id": wh_id,
                        "warehouse_name": wh["name"],
                        "location": wh["location"],
                        "available_quantity": qty,
                        "satisfies_request": True,
                    })
                elif qty > 0:
                    matches.append({
                        "warehouse_id": wh_id,
                        "warehouse_name": wh["name"],
                        "location": wh["location"],
                        "available_quantity": qty,
                        "satisfies_request": False,
                    })
        
        return {
            "success": True,
            "sku": clean_sku,
            "required_qty": required_qty,
            "target_location": target_location,
            "warehouses_with_stock": matches,
            "total_viable_warehouses": len([m for m in matches if m["satisfies_request"]]),
        }


def allocate_stock(sku: str, quantity: int, source_warehouse_id: str, target_shipment_id: str) -> Dict[str, Any]:
    """Allocates inventory from a distribution center for emergency shipment dispatch.
    
    Args:
        sku: SKU identifier to reserve.
        quantity: Number of units to allocate.
        source_warehouse_id: The ID of the warehouse (e.g. 'DC-EASTCOAST').
        target_shipment_id: The shipment ID to assign the inventory to.
        
    Returns:
        Confirmation status, remaining stock at warehouse, and reservation ID.
    """
    clean_sku = sku.strip().upper()
    clean_wh = source_warehouse_id.strip().upper()
    with trace_span("tool.allocate_stock", {"sku": clean_sku, "qty": quantity, "warehouse": clean_wh}):
        if quantity <= 0:
            return {"success": False, "error": "Quantity must be greater than zero."}
        
        with _INVENTORY_LOCK:
            wh = _WAREHOUSE_STOCK.get(clean_wh)
            if not wh:
                return {"success": False, "error": f"Warehouse '{clean_wh}' does not exist."}
            
            curr_stock = wh["stock"].get(clean_sku, 0)
            if curr_stock < quantity:
                return {
                    "success": False,
                    "error": f"Insufficient stock at {clean_wh}. Requested: {quantity}, Available: {curr_stock}.",
                }
            
            wh["stock"][clean_sku] -= quantity
            reservation_id = f"RESV-{clean_wh}-{clean_sku}-{quantity}"
            
            AuditLogger.log_event("inventory.allocated", {
                "sku": clean_sku,
                "quantity": quantity,
                "warehouse": clean_wh,
                "target_shipment_id": target_shipment_id,
                "reservation_id": reservation_id,
            })
            
            return {
                "success": True,
                "reservation_id": reservation_id,
                "allocated_quantity": quantity,
                "remaining_stock": wh["stock"][clean_sku],
                "warehouse": clean_wh,
            }
