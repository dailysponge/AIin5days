"""Tests for Context & Memory management."""

import shutil
import tempfile
from pathlib import Path

import pytest
from logiroute.memory.session_store import (
    IncidentResolutionRecord,
    LogisticsMemoryStore,
    SessionState,
)


@pytest.fixture
def temp_store():
    """Fixture providing an isolated temporary memory store."""
    temp_dir = tempfile.mkdtemp()
    store = LogisticsMemoryStore(storage_dir=temp_dir)
    yield store
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_customer_profile_lookup(temp_store):
    """Verify customer profile retrieval and SLA parameters."""
    profile = temp_store.get_customer_profile("CUST-VIP-001")
    assert profile is not None
    assert profile.customer_id == "CUST-VIP-001"
    assert profile.sla_tier == "VIP_CRITICAL"
    assert profile.auto_reroute_budget_usd == 500.00
    assert "AirFast Global" in profile.preferred_carriers


def test_customer_profile_not_found(temp_store):
    """Verify non-existent customer profile returns None."""
    profile = temp_store.get_customer_profile("NON_EXISTENT")
    assert profile is None


def test_session_lifecycle(temp_store):
    """Verify session creation, updating, and persistence."""
    sess = temp_store.get_or_create_session("test-sess-1", user_id="test_user")
    assert sess.session_id == "test-sess-1"
    assert sess.dialogue_turn_count == 0
    assert sess.active_shipment_id is None

    sess.active_shipment_id = "SHP-MED001"
    sess.dialogue_turn_count = 2
    temp_store.save_session(sess)

    # Re-fetch from store to verify disk persistence
    reloaded = temp_store.get_or_create_session("test-sess-1")
    assert reloaded.active_shipment_id == "SHP-MED001"
    assert reloaded.dialogue_turn_count == 2


def test_incident_resolution_history(temp_store):
    """Verify logging and retrieval of historical incident resolutions."""
    record = IncidentResolutionRecord(
        incident_id="INC-001",
        shipment_id="SHP-MED001",
        issue_type="COLD_CHAIN_ALERT",
        resolution_action="Air freight transfer",
        cost_delta_usd=380.00,
        resolved_at="2026-08-28T00:00:00Z",
        approved_by="dispatcher_dan",
    )
    temp_store.record_incident_resolution(record)

    similar = temp_store.find_similar_past_resolutions("COLD_CHAIN_ALERT")
    assert len(similar) == 1
    assert similar[0]["incident_id"] == "INC-001"
    assert similar[0]["cost_delta_usd"] == 380.00
