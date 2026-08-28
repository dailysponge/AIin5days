"""Strategic Model Routing: Dynamic selection between Fast Tier and Deep Reasoning Tier models."""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

from logiroute.config import config
from logiroute.telemetry.tracing import AuditLogger, trace_span


class ModelTier(str, Enum):
    FAST_TIER = "FAST_TIER"            # e.g., gemini-2.5-flash (low latency, high throughput)
    REASONING_TIER = "REASONING_TIER"  # e.g., gemini-2.5-pro (complex tradeoffs, multi-constraint planning)


@dataclass
class ModelRouteDecision:
    tier: ModelTier
    model_name: str
    rationale: str
    complexity_score: float  # 0.0 to 1.0


class StrategicModelRouter:
    """Intelligently routes dispatcher queries to optimal model tiers based on complexity and urgency."""

    FAST_MODEL = "gemini-2.5-flash"
    REASONING_MODEL = "gemini-2.5-pro"

    @classmethod
    def route_query(cls, query: str, context_metadata: Optional[Dict[str, Any]] = None) -> ModelRouteDecision:
        """Determines the appropriate model tier for processing the request.
        
        Args:
            query: Dispatcher inquiry or system alert text.
            context_metadata: Additional context such as shipment properties or cold chain status.
            
        Returns:
            ModelRouteDecision containing selected tier, model name, and justification.
        """
        with trace_span("model_router.route", {"query_preview": query[:80]}):
            q_lower = query.lower()
            complexity = 0.2
            reasons = []

            # 1. Check for emergency / high-stakes keywords
            if any(term in q_lower for term in ("emergency", "critical", "spiking", "breach", "fail", "vaccine", "cold chain")):
                complexity += 0.5
                reasons.append("P0 Critical Cold-Chain / Life-Sciences incident detected")

            # 2. Check for multi-constraint tradeoff keywords
            if any(term in q_lower for term in ("reroute", "detour", "tradeoff", "blizzard", "closure", "optimize", "compare")):
                complexity += 0.3
                reasons.append("Multi-modal rerouting and SLA trade-off optimization required")

            # 3. Inspect context metadata if available
            if context_metadata:
                if context_metadata.get("is_cold_chain"):
                    complexity += 0.3
                    reasons.append("Active shipment requires strict cold-chain compliance")
                if context_metadata.get("delay_minutes", 0) > 120:
                    complexity += 0.2
                    reasons.append("Severe transit delay (> 2 hours)")

            # Select tier based on complexity score
            if complexity >= 0.6:
                decision = ModelRouteDecision(
                    tier=ModelTier.REASONING_TIER,
                    model_name=cls.REASONING_MODEL,
                    rationale="; ".join(reasons) or "High complexity multi-factor logistics disruption",
                    complexity_score=min(1.0, complexity),
                )
            else:
                decision = ModelRouteDecision(
                    tier=ModelTier.FAST_TIER,
                    model_name=cls.FAST_MODEL,
                    rationale="Routine tracking query or standard status inquiry suitable for fast-tier throughput",
                    complexity_score=complexity,
                )

            AuditLogger.log_event("model_router.decision", {
                "selected_tier": decision.tier.value,
                "model_name": decision.model_name,
                "complexity_score": decision.complexity_score,
                "rationale": decision.rationale,
            })

            return decision


model_router = StrategicModelRouter()
