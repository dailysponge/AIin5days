"""Tests for Context & Memory management including Async SQLite, Vector Store, and Context Bloat."""

import shutil
import tempfile
from pathlib import Path

import pytest
from logiroute.memory.context_manager import ContextManager, context_manager
from logiroute.memory.session_store import (
    IncidentResolutionRecord,
    LogisticsMemoryStore,
    SessionState,
)
from logiroute.memory.vector_store import SemanticVectorStore


@pytest.fixture
def temp_store():
    """Fixture providing an isolated temporary memory store with SQLite."""
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
    """Verify session creation, updating, and persistence in SQLite."""
    sess = temp_store.get_or_create_session("test-sess-1", user_id="test_user")
    assert sess.session_id == "test-sess-1"
    assert sess.dialogue_turn_count == 0
    assert sess.active_shipment_id is None

    sess.active_shipment_id = "SHP-MED001"
    sess.dialogue_turn_count = 2
    temp_store.save_session(sess)

    # Re-fetch from store to verify SQLite disk persistence
    reloaded = temp_store.get_or_create_session("test-sess-1")
    assert reloaded.active_shipment_id == "SHP-MED001"
    assert reloaded.dialogue_turn_count == 2


@pytest.mark.asyncio
async def test_async_session_and_messages(temp_store):
    """Verify async session operations and message history storage."""
    sess = await temp_store.get_or_create_session_async("async-sess-1", user_id="dispatcher_42")
    assert sess.session_id == "async-sess-1"

    await temp_store.add_message_async("async-sess-1", "user", "Where is shipment SHP-ELC002?")
    await temp_store.add_message_async("async-sess-1", "assistant", "Shipment SHP-ELC002 is held up due to blizzard.")

    reloaded = await temp_store.get_or_create_session_async("async-sess-1")
    assert len(reloaded.messages) == 2
    assert reloaded.messages[0]["content"] == "Where is shipment SHP-ELC002?"


@pytest.mark.asyncio
async def test_semantic_vector_store_retrieval(temp_store):
    """Verify semantic vector search returns matching historical resolutions by cosine similarity."""
    record = IncidentResolutionRecord(
        incident_id="INC-VEC-001",
        shipment_id="SHP-MED001",
        issue_type="COLD_CHAIN_ALERT",
        resolution_action="Emergency dry-ice air container reroute",
        cost_delta_usd=380.00,
        resolved_at="2026-08-28T00:00:00Z",
        approved_by="lead_dispatcher",
        description="Severe vaccine temperature spike due to compressor failure",
    )
    await temp_store.record_incident_resolution_async(record)

    # Search with semantically related query terms
    results = await temp_store.find_similar_past_resolutions_async(
        "temperature compressor breach vaccine",
        top_k=2,
    )
    assert len(results) >= 1
    assert any(r["incident_id"] == "INC-VEC-001" for r in results)


def test_context_bloat_sliding_window():
    """Verify sliding window prunes messages and produces a rolling summary when turns exceed limit."""
    cm = ContextManager(max_turns=2)  # max 4 messages (2 turns)
    
    messages = [
        {"role": "user", "content": "Track shipment SHP-MED001 immediately."},
        {"role": "assistant", "content": "Cold-chain alert detected on SHP-MED001. Telemetry is 9.4 C."},
        {"role": "user", "content": "Calculate air freight reroute options."},
        {"role": "assistant", "content": "Reroute option OPT-AIR-EXPRESS calculated at $380."},
        {"role": "user", "content": "Request approval for this reroute."},
        {"role": "assistant", "content": "Approval ticket APPR-AUTO-1234 created and AUTO_APPROVED."},
    ]
    
    # 6 messages exceed max_messages=4
    compacted, summary = cm.compact_context(messages)
    
    # Active window should only retain the 4 most recent messages
    assert len(compacted) == 4
    assert compacted[0]["content"] == "Calculate air freight reroute options."
    
    # Summary should capture the earlier pruned turns
    assert "Summary of earlier turns" in summary
    assert "SHP-MED001" in summary
