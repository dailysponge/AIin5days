"""Production-ready FastAPI REST server for LogiRoute Agent."""

from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from logiroute.config import config
from logiroute.orchestration import LogisticsOrchestrator
from logiroute.telemetry.tracing import AuditLogger
from logiroute.tools import (
    calculate_reroute_options,
    submit_human_approval,
    track_shipment,
)

# Request & Response Schemas
class DispatchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000, description="Dispatcher natural language query or alert")
    session_id: Optional[str] = Field(None, description="Optional session ID for multi-turn conversational context")
    user_id: Optional[str] = Field("api_dispatcher", description="Identifier of the user or system calling the API")


class DispatchResponse(BaseModel):
    session_id: str
    correlation_id: str
    status: str
    mode: str
    response: str
    tools_invoked: List[str]
    active_shipment_id: Optional[str] = None


class ApprovalRequest(BaseModel):
    approval_id: str = Field(..., description="Approval ticket identifier (APPR-HITL-XXXX)")
    approved: bool = Field(..., description="True to authorize, False to reject")
    reviewer_id: str = Field(..., description="Username or employee ID of reviewing dispatcher")
    reason: Optional[str] = Field("", description="Optional comment or justification")


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


orchestrator: LogisticsOrchestrator = LogisticsOrchestrator()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for API logging."""
    AuditLogger.log_event("api.server_started", {
        "service": config.telemetry.service_name,
        "version": config.telemetry.service_version,
    })
    yield
    AuditLogger.log_event("api.server_stopped", {})


app = FastAPI(
    title="LogiRoute Agent API",
    description="Autonomous Logistics & Disruption Resolution Agent powered by Google Cloud ADK",
    version=config.telemetry.service_version,
    lifespan=lifespan,
)

# CORS middleware for secure integration with frontend dashboards
allowed_origins = [o.strip() for o in config.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/healthz", response_model=HealthResponse, tags=["System"])
def health_check():
    """Liveness & readiness probe for Cloud Run and Kubernetes."""
    return HealthResponse(
        status="healthy",
        service=config.telemetry.service_name,
        version=config.telemetry.service_version,
    )


@app.post("/api/v1/dispatch", response_model=DispatchResponse, tags=["Dispatch"])
def dispatch_query(request: DispatchRequest):
    """Processes a natural language logistics request through the ADK agent workflow."""
    if not orchestrator:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Orchestrator not ready.")
    
    result = orchestrator.process_query(
        query=request.query,
        session_id=request.session_id,
        user_id=request.user_id or "api_dispatcher",
    )
    return DispatchResponse(
        session_id=result["session_id"],
        correlation_id=result["correlation_id"],
        status=result["status"],
        mode=result["mode"],
        response=result["response"],
        tools_invoked=result.get("tools_invoked", []),
        active_shipment_id=result.get("active_shipment_id"),
    )


@app.get("/api/v1/shipments/{shipment_id}", tags=["Shipments"])
def get_shipment_status(shipment_id: str):
    """Retrieves direct tracking status and sensor readings for a shipment."""
    result = track_shipment(shipment_id)
    if not result.get("success"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result.get("error"))
    return result


@app.post("/api/v1/shipments/{shipment_id}/reroute", tags=["Shipments"])
def calculate_shipment_reroute(shipment_id: str, issue_type: str = "WEATHER_DELAY"):
    """Calculates rerouting strategies and cost/time trade-offs for a delayed shipment."""
    result = calculate_reroute_options(shipment_id, issue_type)
    if not result.get("success"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.get("error"))
    return result


@app.post("/api/v1/approval", tags=["Guardrails"])
def submit_approval(request: ApprovalRequest):
    """Submits a human dispatcher decision on a pending high-cost HITL ticket."""
    result = submit_human_approval(
        approval_id=request.approval_id,
        approved=request.approved,
        reviewer_id=request.reviewer_id,
        reason=request.reason or "",
    )
    if not result.get("success"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result.get("error"))
    return result
