"""Context and Memory Management for LogiRoute Agent with Async SQLite and Vector Search."""

import asyncio
import json
import os
import sqlite3
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

from logiroute.config import config
from logiroute.memory.context_manager import context_manager
from logiroute.memory.vector_store import SemanticVectorStore
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
    """Historical record of resolved shipment disruptions with vector embedding."""
    incident_id: str
    shipment_id: str
    issue_type: str
    resolution_action: str
    cost_delta_usd: float
    resolved_at: str
    approved_by: str
    description: str = ""
    embedding: Dict[str, float] = field(default_factory=dict)


@dataclass
class SessionState:
    """Working context and short-term memory for active dispatch sessions."""
    session_id: str
    user_id: str
    active_shipment_id: Optional[str] = None
    pending_approval: Optional[Dict[str, Any]] = None
    dialogue_turn_count: int = 0
    summary: str = ""
    messages: List[Dict[str, str]] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)


class LogisticsMemoryStore:
    """Async SQLite database and semantic vector store for persistent logistics memory."""

    def __init__(self, storage_dir: Optional[str] = None):
        self.storage_dir = Path(storage_dir or config.storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.storage_dir / "logistics_memory.db"
        self._lock = threading.Lock()
        
        # In-memory customer cache for instant synchronous lookups
        self._customer_cache: Dict[str, CustomerProfile] = {}
        self._init_db_sync()

    def _init_db_sync(self) -> None:
        """Synchronously initialize SQLite schema and seed defaults."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            cursor = conn.cursor()
            
            # 1. Sessions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    active_shipment_id TEXT,
                    pending_approval TEXT,
                    dialogue_turn_count INTEGER,
                    summary TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    metadata TEXT
                );
            """)
            
            # 2. Messages table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    role TEXT,
                    content TEXT,
                    created_at TEXT
                );
            """)

            # 3. Customer profiles table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS customer_profiles (
                    customer_id TEXT PRIMARY KEY,
                    company_name TEXT,
                    sla_tier TEXT,
                    auto_reroute_budget_usd REAL,
                    preferred_carriers TEXT,
                    contact_channel TEXT,
                    notification_endpoint TEXT
                );
            """)

            # 4. Incident resolution history table with embedding vector
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS incident_resolutions (
                    incident_id TEXT PRIMARY KEY,
                    shipment_id TEXT,
                    issue_type TEXT,
                    resolution_action TEXT,
                    cost_delta_usd REAL,
                    resolved_at TEXT,
                    approved_by TEXT,
                    description TEXT,
                    embedding TEXT
                );
            """)
            
            conn.commit()

            # Seed default customer profiles if empty
            cursor.execute("SELECT COUNT(*) FROM customer_profiles;")
            if cursor.fetchone()[0] == 0:
                defaults = [
                    ("CUST-VIP-001", "Apex Healthcare Supplies", "VIP_CRITICAL", 500.00,
                     json.dumps(["AirFast Global", "SwiftFleet Express"]), "EMAIL", "critical-ops@apexhealth.com"),
                    ("CUST-ENT-002", "OmniRetail Electronics", "ENTERPRISE_PREMIUM", 200.00,
                     json.dumps(["SwiftFleet Express", "FreightMaster Ground"]), "WEBHOOK", "https://api.omniretail.example/webhooks/shipments"),
                    ("CUST-STD-003", "EcoPackaging Direct", "STANDARD", 50.00,
                     json.dumps(["FreightMaster Ground"]), "SMS", "+1-555-019-2834"),
                ]
                cursor.executemany("""
                    INSERT INTO customer_profiles (
                        customer_id, company_name, sla_tier, auto_reroute_budget_usd,
                        preferred_carriers, contact_channel, notification_endpoint
                    ) VALUES (?, ?, ?, ?, ?, ?, ?);
                """, defaults)
                conn.commit()

            # Seed default incident resolution history if empty
            cursor.execute("SELECT COUNT(*) FROM incident_resolutions;")
            if cursor.fetchone()[0] == 0:
                initial_incidents = [
                    (
                        "APPR-HIST-001", "SHP-MED001", "COLD_CHAIN_ALERT",
                        "Immediate dry-ice specialty air freight transfer", 380.00,
                        "2026-01-15T10:00:00Z", "DISPATCHER_LEAD",
                        "Vaccine shipment cold-chain compressor failure requiring emergency air freight",
                        json.dumps(SemanticVectorStore.create_embedding("Vaccine shipment cold-chain compressor failure requiring emergency air freight")),
                    ),
                    (
                        "APPR-HIST-002", "SHP-ELC002", "WEATHER_DELAY",
                        "Southern detour via I-80 to bypass mountain pass closure", 120.00,
                        "2026-02-01T14:30:00Z", "DISPATCHER_SARAH",
                        "Severe mountain pass snowstorm blizzard closure rerouting via southern corridor",
                        json.dumps(SemanticVectorStore.create_embedding("Severe mountain pass snowstorm blizzard closure rerouting via southern corridor")),
                    ),
                ]
                cursor.executemany("""
                    INSERT INTO incident_resolutions (
                        incident_id, shipment_id, issue_type, resolution_action,
                        cost_delta_usd, resolved_at, approved_by, description, embedding
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, initial_incidents)
                conn.commit()

            # Populate in-memory cache for fast sync lookups
            cursor.execute("SELECT * FROM customer_profiles;")
            for row in cursor.fetchall():
                self._customer_cache[row[0]] = CustomerProfile(
                    customer_id=row[0],
                    company_name=row[1],
                    sla_tier=row[2],
                    auto_reroute_budget_usd=row[3],
                    preferred_carriers=json.loads(row[4]),
                    contact_channel=row[5],
                    notification_endpoint=row[6],
                )

            conn.close()

    # --- Async Database Operations ---

    async def get_or_create_session_async(self, session_id: str, user_id: str = "default_dispatcher") -> SessionState:
        """Asynchronously retrieves existing session or initializes a new session state."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    # Fetch recent messages
                    async with db.execute("SELECT role, content FROM messages WHERE session_id = ? ORDER BY id ASC", (session_id,)) as msg_cursor:
                        msg_rows = await msg_cursor.fetchall()
                        messages = [{"role": r[0], "content": r[1]} for r in msg_rows]

                    return SessionState(
                        session_id=row[0],
                        user_id=row[1],
                        active_shipment_id=row[2],
                        pending_approval=json.loads(row[3]) if row[3] else None,
                        dialogue_turn_count=row[4],
                        summary=row[5] or "",
                        messages=messages,
                        created_at=row[6],
                        updated_at=row[7],
                        metadata=json.loads(row[8]) if row[8] else {},
                    )

            # Create new session
            now = datetime.now(timezone.utc).isoformat()
            new_sess = SessionState(session_id=session_id, user_id=user_id, created_at=now, updated_at=now)
            await db.execute("""
                INSERT INTO sessions (
                    session_id, user_id, active_shipment_id, pending_approval,
                    dialogue_turn_count, summary, created_at, updated_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                session_id, user_id, None, None, 0, "", now, now, json.dumps({}),
            ))
            await db.commit()
            return new_sess

    async def save_session_async(self, session: SessionState) -> None:
        """Asynchronously saves session state and applies context bloat sliding-window compaction."""
        session.updated_at = datetime.now(timezone.utc).isoformat()
        
        # Apply sliding window and rolling summarization
        compacted_msgs, updated_summary = context_manager.compact_context(
            session.messages,
            existing_summary=session.summary,
        )
        session.messages = compacted_msgs
        session.summary = updated_summary

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO sessions (
                    session_id, user_id, active_shipment_id, pending_approval,
                    dialogue_turn_count, summary, created_at, updated_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                session.session_id,
                session.user_id,
                session.active_shipment_id,
                json.dumps(session.pending_approval) if session.pending_approval else None,
                session.dialogue_turn_count,
                session.summary,
                session.created_at,
                session.updated_at,
                json.dumps(session.metadata),
            ))
            await db.commit()

    async def add_message_async(self, session_id: str, role: str, content: str) -> None:
        """Asynchronously records a message turn in the database."""
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO messages (session_id, role, content, created_at)
                VALUES (?, ?, ?, ?);
            """, (session_id, role, content, now))
            await db.commit()

    async def record_incident_resolution_async(self, record: IncidentResolutionRecord) -> None:
        """Asynchronously records an incident resolution with semantic embedding into SQLite."""
        if not record.description:
            record.description = f"{record.issue_type} for shipment {record.shipment_id}: {record.resolution_action}"
        if not record.embedding:
            record.embedding = SemanticVectorStore.create_embedding(record.description)

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO incident_resolutions (
                    incident_id, shipment_id, issue_type, resolution_action,
                    cost_delta_usd, resolved_at, approved_by, description, embedding
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                record.incident_id,
                record.shipment_id,
                record.issue_type,
                record.resolution_action,
                record.cost_delta_usd,
                record.resolved_at,
                record.approved_by,
                record.description,
                json.dumps(record.embedding),
            ))
            await db.commit()
            AuditLogger.log_event("memory.resolution_recorded_async", {
                "incident_id": record.incident_id,
                "shipment_id": record.shipment_id,
            })

    async def find_similar_past_resolutions_async(self, query_text: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """Asynchronously searches past incident resolutions using vector cosine similarity."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT incident_id, shipment_id, issue_type, resolution_action, cost_delta_usd, description, embedding FROM incident_resolutions") as cursor:
                rows = await cursor.fetchall()
                corpus = []
                for r in rows:
                    corpus.append({
                        "incident_id": r[0],
                        "shipment_id": r[1],
                        "issue_type": r[2],
                        "resolution_action": r[3],
                        "cost_delta_usd": r[4],
                        "description": r[5],
                        "embedding": json.loads(r[6]) if r[6] else {},
                    })
                
                matches = SemanticVectorStore.find_top_k(query_text, corpus, text_key="description", top_k=top_k)
                return [m[0] for m in matches]

    # --- Synchronous Wrappers for Compatibility ---

    @staticmethod
    def _run_async(coro_func, *args, **kwargs):
        """Safely executes an async coroutine function from synchronous code without loop collisions."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(lambda: asyncio.run(coro_func(*args, **kwargs))).result()
        else:
            return asyncio.run(coro_func(*args, **kwargs))

    def get_customer_profile(self, customer_id: str) -> Optional[CustomerProfile]:
        """Fetch customer profile from fast in-memory cache or database."""
        return self._customer_cache.get(customer_id)

    def get_or_create_session(self, session_id: str, user_id: str = "default_dispatcher") -> SessionState:
        """Synchronous wrapper to retrieve or create session."""
        return self._run_async(self.get_or_create_session_async, session_id, user_id)

    def save_session(self, session: SessionState) -> None:
        """Synchronous wrapper to persist session."""
        self._run_async(self.save_session_async, session)

    def record_incident_resolution(self, record: IncidentResolutionRecord) -> None:
        """Synchronous wrapper to record incident resolution."""
        self._run_async(self.record_incident_resolution_async, record)

    def find_similar_past_resolutions(self, query_text: str, limit: int = 3) -> List[Dict[str, Any]]:
        """Synchronous wrapper to query semantic vector store."""
        return self._run_async(self.find_similar_past_resolutions_async, query_text, top_k=limit)


# Global memory store instance
memory_store = LogisticsMemoryStore()
