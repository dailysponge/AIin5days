"""Human-in-the-Loop approval gate and notification dispatch tools for LogiRoute Agent using strict Pydantic schemas."""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union

from logiroute.config import config
from logiroute.memory.session_store import (
    IncidentResolutionRecord,
    memory_store,
)
from logiroute.telemetry.tracing import AuditLogger, trace_span
from logiroute.tools.schemas import (
    ApprovalInput,
    ApprovalOutput,
    HumanApprovalDecisionInput,
    HumanApprovalDecisionOutput,
    NotificationChannel,
    NotificationInput,
    NotificationOutput,
)

# In-memory tracking of pending HITL approvals
_PENDING_APPROVALS: Dict[str, Dict[str, Any]] = {}


def request_dispatch_approval(
    shipment_id: Union[str, ApprovalInput],
    action_type: Optional[str] = None,
    cost_delta_usd: Optional[float] = None,
    rationale: Optional[str] = None,
    customer_id: Optional[str] = None,
) -> ApprovalOutput:
    """Evaluates whether an action requires Human-in-the-Loop (HITL) authorization based on cost & SLA guardrails.
    
    Args:
        shipment_id: Affected shipment ID or ApprovalInput.
        action_type: Category of action ('AIR_EXPEDITE', 'WAREHOUSE_REROUTE', 'DISPOSAL').
        cost_delta_usd: Additional financial cost in USD.
        rationale: Operational justification.
        customer_id: Optional customer ID to inspect customer-specific SLA budget limits.
        
    Returns:
        ApprovalOutput indicating approval status, budget threshold, and ticket ID.
    """
    if isinstance(shipment_id, ApprovalInput):
        clean_id = shipment_id.shipment_id.strip().upper()
        act_type = shipment_id.action_type
        cost = shipment_id.cost_delta_usd
        rat = shipment_id.rationale
        cust_id = shipment_id.customer_id
    else:
        clean_id = str(shipment_id).strip().upper()
        act_type = str(action_type or "REROUTE")
        cost = float(cost_delta_usd or 0.0)
        rat = str(rationale or "Operational disruption mitigation")
        cust_id = customer_id

    with trace_span("tool.request_dispatch_approval", {
        "shipment_id": clean_id,
        "action_type": act_type,
        "cost_delta": cost,
    }):
        threshold = config.security.max_auto_approval_cost_usd
        customer = memory_store.get_customer_profile(cust_id) if cust_id else None
        if customer:
            threshold = customer.auto_reroute_budget_usd
        
        # Check guardrail: Auto-approve if cost is within customer threshold
        if cost <= threshold:
            approval_id = f"APPR-AUTO-{uuid.uuid4().hex[:8].upper()}"
            AuditLogger.log_event("guardrail.auto_approved", {
                "approval_id": approval_id,
                "shipment_id": clean_id,
                "cost_delta_usd": cost,
                "threshold": threshold,
            })
            
            memory_store.record_incident_resolution(IncidentResolutionRecord(
                incident_id=approval_id,
                shipment_id=clean_id,
                issue_type=act_type,
                resolution_action=f"Approved automatically (within budget ${threshold:.2f})",
                cost_delta_usd=cost,
                resolved_at=datetime.now(timezone.utc).isoformat(),
                approved_by="SYSTEM_GUARDRAIL_AUTO",
            ))
            
            return ApprovalOutput(
                status="AUTO_APPROVED",
                approval_id=approval_id,
                cost_delta_usd=cost,
                threshold_applied_usd=threshold,
                message=f"Action automatically approved under allowable budget limit (${threshold:.2f} USD).",
            )
        
        # Exceeds threshold -> Trigger HITL gate
        approval_id = f"APPR-HITL-{uuid.uuid4().hex[:8].upper()}"
        approval_request = {
            "approval_id": approval_id,
            "shipment_id": clean_id,
            "action_type": act_type,
            "cost_delta_usd": cost,
            "threshold_exceeded_by": round(cost - threshold, 2),
            "rationale": rat,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "PENDING",
        }
        _PENDING_APPROVALS[approval_id] = approval_request
        
        AuditLogger.log_event("guardrail.hitl_triggered", {
            "approval_id": approval_id,
            "shipment_id": clean_id,
            "cost_delta_usd": cost,
            "threshold": threshold,
        }, level="WARNING")
        
        return ApprovalOutput(
            status="PENDING_HUMAN_APPROVAL",
            approval_id=approval_id,
            cost_delta_usd=cost,
            threshold_applied_usd=threshold,
            prompt_for_dispatcher=(
                f"ACTION REQUIRED: Proposed action '{act_type}' for shipment {clean_id} "
                f"costs ${cost:.2f} USD, exceeding authorization threshold (${threshold:.2f} USD). "
                f"Dispatcher approval ticket: {approval_id}. Rationale: {rat}"
            ),
        )


def submit_human_approval(
    approval_id: Union[str, HumanApprovalDecisionInput],
    approved: Optional[bool] = None,
    reviewer_id: Optional[str] = None,
    reason: Optional[str] = "",
) -> HumanApprovalDecisionOutput:
    """Submits a human dispatcher decision for a pending HITL authorization ticket.
    
    Args:
        approval_id: The approval ticket identifier or HumanApprovalDecisionInput.
        approved: True to authorize the action, False to reject.
        reviewer_id: Username/ID of the dispatcher authorizing or rejecting.
        reason: Optional review comment.
        
    Returns:
        HumanApprovalDecisionOutput with ticket status and decision audit record.
    """
    if isinstance(approval_id, HumanApprovalDecisionInput):
        appr_id = approval_id.approval_id
        is_approved = approval_id.approved
        rev_id = approval_id.reviewer_id
        comment = approval_id.reason or ""
    else:
        appr_id = str(approval_id)
        is_approved = bool(approved)
        rev_id = str(reviewer_id or "anonymous_dispatcher")
        comment = str(reason or "")

    with trace_span("tool.submit_human_approval", {"approval_id": appr_id, "approved": is_approved, "reviewer": rev_id}):
        ticket = _PENDING_APPROVALS.get(appr_id)
        if not ticket:
            return HumanApprovalDecisionOutput(
                success=False,
                error=f"Approval ticket '{appr_id}' not found or already processed.",
            )
        
        ticket["status"] = "APPROVED" if is_approved else "REJECTED"
        ticket["resolved_at"] = datetime.now(timezone.utc).isoformat()
        ticket["reviewed_by"] = rev_id
        ticket["review_comment"] = comment
        
        AuditLogger.log_event("guardrail.hitl_decided", ticket)
        
        if is_approved:
            memory_store.record_incident_resolution(IncidentResolutionRecord(
                incident_id=appr_id,
                shipment_id=ticket["shipment_id"],
                issue_type=ticket["action_type"],
                resolution_action=f"Manually authorized by dispatcher {rev_id}",
                cost_delta_usd=ticket["cost_delta_usd"],
                resolved_at=datetime.now(timezone.utc).isoformat(),
                approved_by=rev_id,
            ))
        
        return HumanApprovalDecisionOutput(
            success=True,
            ticket=ticket,
        )


def send_customer_notification(
    customer_id: Union[str, NotificationInput],
    shipment_id: Optional[str] = None,
    message: Optional[str] = None,
    channel: Optional[Union[str, NotificationChannel]] = None,
) -> NotificationOutput:
    """Dispatches real-time automated status update and disruption notification to the customer.
    
    Args:
        customer_id: Recipient customer ID or NotificationInput.
        shipment_id: Associated shipment ID.
        message: Transparent status update message.
        channel: Delivery channel ('EMAIL', 'SMS', 'WEBHOOK').
        
    Returns:
        NotificationOutput receipt with delivery confirmation and destination.
    """
    if isinstance(customer_id, NotificationInput):
        clean_cid = customer_id.customer_id.strip().upper()
        clean_shp = customer_id.shipment_id.strip().upper()
        msg_body = customer_id.message
        chan = customer_id.channel.value if customer_id.channel else None
    else:
        clean_cid = str(customer_id).strip().upper()
        clean_shp = str(shipment_id or "").strip().upper()
        msg_body = str(message or "")
        chan = channel.value if hasattr(channel, "value") else (str(channel) if channel else None)

    with trace_span("tool.send_customer_notification", {"customer_id": clean_cid, "shipment_id": clean_shp}):
        customer = memory_store.get_customer_profile(clean_cid)
        target_channel = chan.upper() if chan else (customer.contact_channel if customer else "EMAIL")
        endpoint = customer.notification_endpoint if customer else "customer-alerts@example.com"
        
        dispatch_id = f"NOTIF-{uuid.uuid4().hex[:8].upper()}"
        payload = {
            "notification_id": dispatch_id,
            "customer_id": clean_cid,
            "shipment_id": clean_shp,
            "channel": target_channel,
            "destination_endpoint": endpoint,
            "message_body": msg_body,
            "dispatched_at": datetime.now(timezone.utc).isoformat(),
            "delivery_status": "DELIVERED",
        }
        
        AuditLogger.log_event("notification.dispatched", payload)
        
        return NotificationOutput(
            success=True,
            notification_id=dispatch_id,
            channel=target_channel,
            destination=endpoint,
            delivery_status="DELIVERED",
        )
