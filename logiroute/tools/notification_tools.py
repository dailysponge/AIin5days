"""Human-in-the-Loop approval gate and notification dispatch tools for LogiRoute Agent."""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from logiroute.config import config
from logiroute.memory.session_store import (
    IncidentResolutionRecord,
    memory_store,
)
from logiroute.telemetry.tracing import AuditLogger, trace_span

# In-memory tracking of pending HITL approvals
_PENDING_APPROVALS: Dict[str, Dict[str, Any]] = {}


def request_dispatch_approval(
    shipment_id: str,
    action_type: str,
    cost_delta_usd: float,
    rationale: str,
    customer_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Evaluates whether an action requires Human-in-the-Loop (HITL) authorization based on cost & SLA guardrails.
    
    Args:
        shipment_id: The ID of the affected shipment.
        action_type: Category of action ('AIR_EXPEDITE', 'WAREHOUSE_REROUTE', 'DISPOSAL').
        cost_delta_usd: The additional financial cost in USD for this action.
        rationale: Operational justification explaining why the action is needed.
        customer_id: Optional customer ID to inspect customer-specific SLA budget limits.
        
    Returns:
        Approval status ('AUTO_APPROVED', 'PENDING_HUMAN_APPROVAL') and approval ticket ID.
    """
    clean_id = shipment_id.strip().upper()
    with trace_span("tool.request_dispatch_approval", {
        "shipment_id": clean_id,
        "action_type": action_type,
        "cost_delta": cost_delta_usd,
    }):
        # Determine applicable budget threshold
        threshold = config.security.max_auto_approval_cost_usd
        customer = memory_store.get_customer_profile(customer_id) if customer_id else None
        if customer:
            threshold = customer.auto_reroute_budget_usd
        
        # Check guardrail: Auto-approve if cost is within customer threshold
        if cost_delta_usd <= threshold:
            approval_id = f"APPR-AUTO-{uuid.uuid4().hex[:8].upper()}"
            AuditLogger.log_event("guardrail.auto_approved", {
                "approval_id": approval_id,
                "shipment_id": clean_id,
                "cost_delta_usd": cost_delta_usd,
                "threshold": threshold,
            })
            
            # Record resolution in long-term memory
            memory_store.record_incident_resolution(IncidentResolutionRecord(
                incident_id=approval_id,
                shipment_id=clean_id,
                issue_type=action_type,
                resolution_action=f"Approved automatically (within budget ${threshold:.2f})",
                cost_delta_usd=cost_delta_usd,
                resolved_at=datetime.now(timezone.utc).isoformat(),
                approved_by="SYSTEM_GUARDRAIL_AUTO",
            ))
            
            return {
                "status": "AUTO_APPROVED",
                "approval_id": approval_id,
                "cost_delta_usd": cost_delta_usd,
                "threshold_applied_usd": threshold,
                "message": f"Action automatically approved under allowable budget limit (${threshold:.2f} USD).",
            }
        
        # Exceeds threshold -> Trigger HITL gate
        approval_id = f"APPR-HITL-{uuid.uuid4().hex[:8].upper()}"
        approval_request = {
            "approval_id": approval_id,
            "shipment_id": clean_id,
            "action_type": action_type,
            "cost_delta_usd": cost_delta_usd,
            "threshold_exceeded_by": round(cost_delta_usd - threshold, 2),
            "rationale": rationale,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "PENDING",
        }
        _PENDING_APPROVALS[approval_id] = approval_request
        
        AuditLogger.log_event("guardrail.hitl_triggered", {
            "approval_id": approval_id,
            "shipment_id": clean_id,
            "cost_delta_usd": cost_delta_usd,
            "threshold": threshold,
        }, level="WARNING")
        
        return {
            "status": "PENDING_HUMAN_APPROVAL",
            "approval_id": approval_id,
            "cost_delta_usd": cost_delta_usd,
            "threshold_applied_usd": threshold,
            "prompt_for_dispatcher": (
                f"ACTION REQUIRED: Proposed action '{action_type}' for shipment {clean_id} "
                f"costs ${cost_delta_usd:.2f} USD, exceeding authorization threshold (${threshold:.2f} USD). "
                f"Dispatcher approval ticket: {approval_id}. Rationale: {rationale}"
            ),
        }


def submit_human_approval(approval_id: str, approved: bool, reviewer_id: str, reason: str = "") -> Dict[str, Any]:
    """Submits a human dispatcher decision for a pending HITL authorization ticket.
    
    Args:
        approval_id: The approval ticket identifier.
        approved: True to authorize the action, False to reject.
        reviewer_id: The username/ID of the dispatcher authorizing or rejecting.
        reason: Optional review comment.
        
    Returns:
        Updated ticket status and decision audit record.
    """
    with trace_span("tool.submit_human_approval", {"approval_id": approval_id, "approved": approved, "reviewer": reviewer_id}):
        ticket = _PENDING_APPROVALS.get(approval_id)
        if not ticket:
            return {
                "success": False,
                "error": f"Approval ticket '{approval_id}' not found or already processed.",
            }
        
        ticket["status"] = "APPROVED" if approved else "REJECTED"
        ticket["resolved_at"] = datetime.now(timezone.utc).isoformat()
        ticket["reviewed_by"] = reviewer_id
        ticket["review_comment"] = reason
        
        AuditLogger.log_event("guardrail.hitl_decided", ticket)
        
        if approved:
            memory_store.record_incident_resolution(IncidentResolutionRecord(
                incident_id=approval_id,
                shipment_id=ticket["shipment_id"],
                issue_type=ticket["action_type"],
                resolution_action=f"Manually authorized by dispatcher {reviewer_id}",
                cost_delta_usd=ticket["cost_delta_usd"],
                resolved_at=datetime.now(timezone.utc).isoformat(),
                approved_by=reviewer_id,
            ))
        
        return {
            "success": True,
            "ticket": ticket,
        }


def send_customer_notification(
    customer_id: str,
    shipment_id: str,
    message: str,
    channel: Optional[str] = None,
) -> Dict[str, Any]:
    """Dispatches real-time automated status update and disruption notification to the customer.
    
    Args:
        customer_id: The recipient customer ID (e.g. 'CUST-VIP-001').
        shipment_id: The shipment ID associated with the notification.
        message: The transparent, professional message explaining status and mitigation.
        channel: Delivery channel ('EMAIL', 'SMS', 'WEBHOOK'). Defaults to customer profile preference.
        
    Returns:
        Notification dispatch receipt with timestamp and delivery channel.
    """
    clean_cid = customer_id.strip().upper()
    with trace_span("tool.send_customer_notification", {"customer_id": clean_cid, "shipment_id": shipment_id}):
        customer = memory_store.get_customer_profile(clean_cid)
        target_channel = channel.upper() if channel else (customer.contact_channel if customer else "EMAIL")
        endpoint = customer.notification_endpoint if customer else "customer-alerts@example.com"
        
        dispatch_id = f"NOTIF-{uuid.uuid4().hex[:8].upper()}"
        payload = {
            "notification_id": dispatch_id,
            "customer_id": clean_cid,
            "shipment_id": shipment_id,
            "channel": target_channel,
            "destination_endpoint": endpoint,
            "message_body": message,
            "dispatched_at": datetime.now(timezone.utc).isoformat(),
            "delivery_status": "DELIVERED",
        }
        
        AuditLogger.log_event("notification.dispatched", payload)
        
        return {
            "success": True,
            "notification_id": dispatch_id,
            "channel": target_channel,
            "destination": endpoint,
            "delivery_status": "DELIVERED",
        }
