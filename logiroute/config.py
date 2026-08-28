"""Configuration settings for LogiRoute Agent."""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class SecurityPolicy:
    """Security and operational guardrail thresholds."""
    max_auto_approval_cost_usd: float = 150.00
    require_hitl_for_hazardous: bool = True
    require_hitl_for_cold_chain_breach: bool = True
    max_input_length_chars: int = 4000
    rate_limit_per_minute: int = 60


@dataclass(frozen=True)
class TelemetryConfig:
    """Telemetry and observability configuration."""
    service_name: str = "logiroute-agent"
    service_version: str = "1.0.0"
    enable_console_export: bool = True
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))


@dataclass(frozen=True)
class AppConfig:
    """Central configuration for LogiRoute system."""
    model_name: str = field(default_factory=lambda: os.getenv("MODEL_NAME", "gemini-2.5-flash"))
    google_cloud_project: Optional[str] = field(default_factory=lambda: os.getenv("GOOGLE_CLOUD_PROJECT"))
    gemini_api_key: Optional[str] = field(default_factory=lambda: os.getenv("GEMINI_API_KEY"))
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8080")))
    host: str = field(default_factory=lambda: os.getenv("HOST", "127.0.0.1"))
    cors_origins: str = field(default_factory=lambda: os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8080"))
    storage_dir: str = field(default_factory=lambda: os.getenv("STORAGE_DIR", "./data/sessions"))
    security: SecurityPolicy = field(default_factory=SecurityPolicy)
    telemetry: TelemetryConfig = field(default_factory=TelemetryConfig)


# Global default configuration instance
config = AppConfig()
