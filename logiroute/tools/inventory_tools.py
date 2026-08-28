"""Inventory and warehouse distribution tools for LogiRoute Agent using strict Pydantic schemas."""

import threading
from typing import Any, Dict, List, Optional, Union

from logiroute.telemetry.tracing import AuditLogger, trace_span
from logiroute.tools.schemas import (
    AllocateStockInput,
    AllocateStockOutput,
    LocateInventoryInput,
    LocateInventoryOutput,
    WarehouseStockDetail,
)

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


def locate_inventory(
    sku: Union[str, LocateInventoryInput],
    required_qty: Optional[int] = None,
    target_location: Optional[str] = None,
) -> LocateInventoryOutput:
    """Queries distribution centers across the network to locate available stock.
    
    Args:
        sku: Stock Keeping Unit identifier (e.g. 'MED-VAX-882') or LocateInventoryInput.
        required_qty: Quantity needed to satisfy demand.
        target_location: Target city/destination for delivery.
        
    Returns:
        LocateInventoryOutput with list of warehouses, availability, and fulfillment viability.
    """
    if isinstance(sku, LocateInventoryInput):
        clean_sku = sku.sku.strip().upper()
        req_qty = sku.required_qty
        tgt_loc = sku.target_location.strip()
    else:
        clean_sku = str(sku).strip().upper()
        req_qty = int(required_qty if required_qty is not None else 1)
        tgt_loc = str(target_location or "National Logistics Hub").strip()

    with trace_span("tool.locate_inventory", {"sku": clean_sku, "required_qty": req_qty, "target_location": tgt_loc}):
        if req_qty <= 0:
            return LocateInventoryOutput(
                success=False,
                sku=clean_sku,
                required_qty=req_qty,
                target_location=tgt_loc,
                error=f"Required quantity must be a positive integer, got {req_qty}.",
            )
        
        matches: List[WarehouseStockDetail] = []
        with _INVENTORY_LOCK:
            for wh_id, wh in _WAREHOUSE_STOCK.items():
                qty = wh["stock"].get(clean_sku, 0)
                if qty >= req_qty:
                    matches.append(WarehouseStockDetail(
                        warehouse_id=wh_id,
                        warehouse_name=wh["name"],
                        location=wh["location"],
                        available_quantity=qty,
                        satisfies_request=True,
                    ))
                elif qty > 0:
                    matches.append(WarehouseStockDetail(
                        warehouse_id=wh_id,
                        warehouse_name=wh["name"],
                        location=wh["location"],
                        available_quantity=qty,
                        satisfies_request=False,
                    ))
        
        return LocateInventoryOutput(
            success=True,
            sku=clean_sku,
            required_qty=req_qty,
            target_location=tgt_loc,
            warehouses_with_stock=matches,
            total_viable_warehouses=len([m for m in matches if m.satisfies_request]),
        )


def allocate_stock(
    sku: Union[str, AllocateStockInput],
    quantity: Optional[int] = None,
    source_warehouse_id: Optional[str] = None,
    target_shipment_id: Optional[str] = None,
) -> AllocateStockOutput:
    """Allocates inventory from a distribution center for emergency shipment dispatch.
    
    Args:
        sku: SKU identifier to reserve or AllocateStockInput.
        quantity: Number of units to allocate.
        source_warehouse_id: The ID of the warehouse (e.g. 'DC-EASTCOAST').
        target_shipment_id: The shipment ID to assign the inventory to.
        
    Returns:
        AllocateStockOutput with confirmation status, remaining stock, and reservation ID.
    """
    if isinstance(sku, AllocateStockInput):
        clean_sku = sku.sku.strip().upper()
        alloc_qty = sku.quantity
        clean_wh = sku.source_warehouse_id.strip().upper()
        clean_shp = sku.target_shipment_id.strip().upper()
    else:
        clean_sku = str(sku).strip().upper()
        alloc_qty = int(quantity if quantity is not None else 1)
        clean_wh = str(source_warehouse_id or "").strip().upper()
        clean_shp = str(target_shipment_id or "").strip().upper()

    with trace_span("tool.allocate_stock", {"sku": clean_sku, "qty": alloc_qty, "warehouse": clean_wh}):
        if alloc_qty <= 0:
            return AllocateStockOutput(success=False, error="Quantity must be greater than zero.")
        
        with _INVENTORY_LOCK:
            wh = _WAREHOUSE_STOCK.get(clean_wh)
            if not wh:
                return AllocateStockOutput(success=False, error=f"Warehouse '{clean_wh}' does not exist.")
            
            curr_stock = wh["stock"].get(clean_sku, 0)
            if curr_stock < alloc_qty:
                return AllocateStockOutput(
                    success=False,
                    error=f"Insufficient stock at {clean_wh}. Requested: {alloc_qty}, Available: {curr_stock}.",
                )
            
            wh["stock"][clean_sku] -= alloc_qty
            reservation_id = f"RESV-{clean_wh}-{clean_sku}-{alloc_qty}"
            
            AuditLogger.log_event("inventory.allocated", {
                "sku": clean_sku,
                "quantity": alloc_qty,
                "warehouse": clean_wh,
                "target_shipment_id": clean_shp,
                "reservation_id": reservation_id,
            })
            
            return AllocateStockOutput(
                success=True,
                reservation_id=reservation_id,
                allocated_quantity=alloc_qty,
                remaining_stock=wh["stock"][clean_sku],
                warehouse=clean_wh,
            )
