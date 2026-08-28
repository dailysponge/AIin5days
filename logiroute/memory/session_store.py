"""Context and Memory Management for LogiRoute Agent."""

import json
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from logiroute.config import config
from logiroute.telemetry.tracing import AuditLogger


@dataclass
class CustomerProfile:
    """Customer profile and SLA parameters stored in long-term memory."""
    customer_id: str
    company_name: str
    sla_tier: str  # e.g., "VIP_CRITICAL", "ENTERPRISE_PREMIUM", "STANDARD"
    auto_reroute_budget_usd: float
    preferred_carriers: List[str] = field(default_factory=list)
    contact_channel: str = "EMAIL"  # "EMAIL", "SMS", "WEBHOOK"
    notification_endpoint: str = "dispatch@example.com"


@dataclass
class IncidentResolutionRecord:
    """Historical record of resolved shipment disruptions."""
    incident_id: str
    shipment_id: str
    issue_type: str
    resolution_action: str
    cost_delta_usd: float
    resolved_at: str
    approved_by: str


@dataclass
class SessionState:
    """Working context and short-term memory for active dispatch sessions."""
    session_id: str
    user_id: str
    active_shipment_id: Optional[str] = None
    pending_approval: Optional[Dict[str, Any]] = None
    dialogue_turn_count: int = 0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)


class LogisticsMemoryStore:
    """Persistent storage and retrieval system for customer SLA memory and resolution history."""

    def __init__(self, storage_dir: Optional[str] = None):
        self.storage_dir = Path(storage_dir or config.storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        
        self._customers_file = self.storage_dir / "customers.json"
        self._history_file = self.storage_dir / "resolution_history.json"
        self._sessions_file = self.storage_dir / "active_sessions.json"
        
        self._init_default_data()

    def _init_default_data(self) -> None:
        """Seed long-term knowledge base with representative logistics profiles."""
        with self._lock:
            if not self._customers_file.exists():
                default_customers = {
                    "CUST-VIP-001": asdict(CustomerProfile(
                        customer_id="CUST-VIP-001",
                        company_name="Apex Healthcare Supplies",
                        sla_tier="VIP_CRITICAL",
                        auto_reroute_budget_usd=500.00,
                        preferred_carriers=["AirFast Global", "SwiftFleet Express"],
                        contact_channel="EMAIL",
                        notification_endpoint="critical-ops@apexhealth.com",
                    )),
                    "CUST-ENT-002": asdict(CustomerProfile(
                        customer_id="CUST-ENT-002",
                        company_name="OmniRetail Electronics",
                        sla_tier="ENTERPRISE_PREMIUM",
                        auto_reroute_budget_usd=200.00,
                        preferred_carriers=["SwiftFleet Express", "FreightMaster Ground"],
                        contact_channel="WEBHOOK",
                        notification_endpoint="https://api.omniretail.example/webhooks/shipments",
                    )),
                    "CUST-STD-003": asdict(CustomerProfile(
                        customer_id="CUST-STD-003",
                        company_name="EcoPackaging Direct",
                        sla_tier="STANDARD",
                        auto_reroute_budget_usd=50.00,
                        preferred_carriers=["FreightMaster Ground"],
                        contact_channel="SMS",
                        notification_endpoint="+1-555-019-2834",
                    )),
                }
                self._customers_file.write_text(json.dumps(default_customers, indent=2))

            if not self._history_file.exists():
                self._history_file.write_text(json.dumps([], indent=2))

            if not self._sessions_file.exists():
                self._sessions_file.write_text(json.dumps({}, indent=2))

    def get_customer_profile(self, customer_id: str) -> Optional[CustomerProfile]:
        """Fetch customer profile and SLA tier from long-term memory."""
        with self._lock:
            try:
                data = json.loads(self._customers_file.read_text())
                raw = data.get(customer_id)
                if raw:
                    return CustomerProfile(**raw)
            except Exception as e:
                AuditLogger.log_event("memory.customer_read_failed", {"error": str(e), "customer_id": customer_id}, level="ERROR")
            return None

    def record_incident_resolution(self, record: IncidentResolutionRecord) -> None:
        """Persist incident resolution to long-term historical memory."""
        with self._lock:
            try:
                records = json.loads(self._history_file.read_text())
                records.append(asdict(record))
                self._history_file.write_text(json.dumps(records, indent=2))
                AuditLogger.log_event("memory.resolution_recorded", {"incident_id": record.incident_id, "shipment_id": record.shipment_id})
            except Exception as e:
                AuditLogger.log_event("memory.resolution_write_failed", {"error": str(e)}, level="ERROR")

    def find_similar_past_resolutions(self, issue_type: str, limit: int = 3) -> List[Dict[str, Any]]:
        """Retrieve successful past resolutions for the same category of issue."""
        with self._lock:
            try:
                records = json.loads(self._history_file.read_text())
                matches = [r for r in records if r.get("issue_type") == issue_type]
                return matches[-limit:]
            except Exception:
                return []

    def get_or_create_session(self, session_id: str, user_id: str = "default_dispatcher") -> SessionState:
        """Retrieve existing working context or initialize a fresh session."""
        with self._lock:
            try:
                sessions = json.loads(self._sessions_file.read_text())
                if session_id in sessions:
                    return SessionState(**sessions[session_id])
                
                new_session = SessionState(session_id=session_id, user_id=user_id)
                sessions[session_id] = asdict(new_session)
                self._sessions_file.write_text(json.dumps(sessions, indent=2))
                return new_session
            except Exception as e:
                AuditLogger.log_event("memory.session_init_failed", {"error": str(e), "session_id": session_id}, level="ERROR")
                return SessionState(session_id=session_id, user_id=user_id)

    def save_session(self, session: SessionState) -> None:
        """Persist session working context updates."""
        with self._lock:
            try:
                session.updated_at = datetime.now(timezone.utc).isoformat()
                sessions = json.loads(self._sessions_file.read_text())
                sessions[session.session_id] = asdict(session)
                self._sessions_file.write_text(json.dumps(sessions, indent=2))
            except Exception as e:
                AuditLogger.log_event("memory.session_save_failed", {"error": str(e), "session_id": session.session_id}, level="ERROR")


# Global memory store instance
memory_store = LogisticsMemoryStore()
