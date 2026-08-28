"""Observability, OpenTelemetry instrumentation, and structured audit logging for LogiRoute."""

import json
import logging
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Generator, Optional

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from logiroute.config import config

# Configure root logger for structured output
logger = logging.getLogger(config.telemetry.service_name)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        fmt='%(asctime)s [%(levelname)s] [%(name)s] %(message)s',
        datefmt='%Y-%m-%dT%H:%M:%SZ',
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, config.telemetry.log_level.upper(), logging.INFO))

tracer = trace.get_tracer(
    config.telemetry.service_name,
    config.telemetry.service_version,
)


class AuditLogger:
    """Structured JSON audit logger for compliance and operations monitoring."""

    @staticmethod
    def _sanitize(data: Any) -> Any:
        """Mask sensitive keys if present."""
        if isinstance(data, dict):
            sanitized = {}
            for k, v in data.items():
                if any(secret in k.lower() for secret in ("token", "key", "password", "secret", "auth")):
                    sanitized[k] = "***MASKED***"
                else:
                    sanitized[k] = AuditLogger._sanitize(v)
            return sanitized
        elif isinstance(data, list):
            return [AuditLogger._sanitize(item) for item in data]
        return data

    @classmethod
    def log_event(
        cls,
        event_type: str,
        details: Dict[str, Any],
        correlation_id: Optional[str] = None,
        level: str = "INFO",
    ) -> None:
        """Emit a structured audit log event."""
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "service": config.telemetry.service_name,
            "version": config.telemetry.service_version,
            "event_type": event_type,
            "correlation_id": correlation_id or str(uuid.uuid4()),
            "details": cls._sanitize(details),
        }
        log_msg = json.dumps(payload, default=str)
        if level.upper() == "WARNING":
            logger.warning(log_msg)
        elif level.upper() == "ERROR":
            logger.error(log_msg)
        else:
            logger.info(log_msg)


@contextmanager
def trace_span(
    name: str,
    attributes: Optional[Dict[str, Any]] = None,
    correlation_id: Optional[str] = None,
) -> Generator[trace.Span, None, None]:
    """Context manager for tracing operations with OpenTelemetry spans and audit logs."""
    cid = correlation_id or str(uuid.uuid4())
    start_time = time.perf_counter()
    
    with tracer.start_as_current_span(name) as span:
        span.set_attribute("logiroute.correlation_id", cid)
        if attributes:
            for k, v in attributes.items():
                span.set_attribute(f"logiroute.{k}", str(v))
        
        AuditLogger.log_event(
            event_type=f"{name}.started",
            details=attributes or {},
            correlation_id=cid,
        )
        
        try:
            yield span
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            span.set_attribute("logiroute.duration_ms", duration_ms)
            span.set_status(Status(StatusCode.OK))
            AuditLogger.log_event(
                event_type=f"{name}.completed",
                details={"duration_ms": round(duration_ms, 2)},
                correlation_id=cid,
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            AuditLogger.log_event(
                event_type=f"{name}.failed",
                details={"duration_ms": round(duration_ms, 2), "error": str(exc)},
                correlation_id=cid,
                level="ERROR",
            )
            raise
