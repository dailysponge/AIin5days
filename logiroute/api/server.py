"""Production-ready FastAPI REST server for LogiRoute Multi-Agent System."""

from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from logiroute.config import config
from logiroute.orchestration import LogisticsOrchestrator
from logiroute.telemetry.tracing import AuditLogger
from logiroute.tools import (
    ApprovalInput,
    ApprovalOutput,
    CalculateRerouteOutput,
    HumanApprovalDecisionInput,
    HumanApprovalDecisionOutput,
    IssueType,
    TrackShipmentOutput,
    calculate_reroute_options,
    submit_human_approval,
    track_shipment,
)

# Request & Response Schemas
class DispatchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000, description="Dispatcher natural language query or alert")
    session_id: Optional[str] = Field(None, description="Optional session ID for multi-turn conversational context")
    user_id: Optional[str] = Field("api_dispatcher", description="Identifier of the user or system calling the API")


class ModelRoutingDetail(BaseModel):
    tier: str
    model_name: str
    rationale: Optional[str] = None
    complexity_score: Optional[float] = None


class DispatchResponse(BaseModel):
    session_id: str
    correlation_id: str
    status: str
    mode: str
    model_routing: Optional[ModelRoutingDetail] = None
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
    title="LogiRoute Multi-Agent Logistics API",
    description="Autonomous Logistics Dispatch & Disruption Resolution Multi-Agent System powered by Google Cloud ADK",
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
async def dispatch_query(request: DispatchRequest, background_tasks: BackgroundTasks):
    """Asynchronously processes a natural language logistics request through multi-agent collaboration."""
    result = await orchestrator.process_query_async(
        query=request.query,
        session_id=request.session_id,
        user_id=request.user_id or "api_dispatcher",
    )
    
    # Asynchronous background task for audit metrics logging
    background_tasks.add_task(
        AuditLogger.log_event,
        "api.dispatch_completed_async",
        {
            "session_id": result["session_id"],
            "correlation_id": result["correlation_id"],
            "tools_count": len(result.get("tools_invoked", [])),
        },
    )

    routing_data = result.get("model_routing")
    model_routing_model = ModelRoutingDetail(**routing_data) if routing_data else None

    return DispatchResponse(
        session_id=result["session_id"],
        correlation_id=result["correlation_id"],
        status=result["status"],
        mode=result["mode"],
        model_routing=model_routing_model,
        response=result["response"],
        tools_invoked=result.get("tools_invoked", []),
        active_shipment_id=result.get("active_shipment_id"),
    )


@app.get("/api/v1/shipments/{shipment_id}", response_model=TrackShipmentOutput, tags=["Shipments"])
def get_shipment_status(shipment_id: str):
    """Retrieves direct tracking status and sensor readings for a shipment."""
    result = track_shipment(shipment_id)
    if not result.success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result.error)
    return result


@app.post("/api/v1/shipments/{shipment_id}/reroute", response_model=CalculateRerouteOutput, tags=["Shipments"])
def calculate_shipment_reroute(shipment_id: str, issue_type: IssueType = IssueType.WEATHER_DELAY):
    """Calculates rerouting strategies and cost/time trade-offs for a delayed shipment."""
    result = calculate_reroute_options(shipment_id, issue_type)
    if not result.success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.error)
    return result


@app.post("/api/v1/approval", response_model=HumanApprovalDecisionOutput, tags=["Guardrails"])
def submit_approval(request: ApprovalRequest):
    """Submits a human dispatcher decision on a pending high-cost HITL ticket."""
    decision_input = HumanApprovalDecisionInput(
        approval_id=request.approval_id,
        approved=request.approved,
        reviewer_id=request.reviewer_id,
        reason=request.reason or "",
    )
    result = submit_human_approval(decision_input)
    if not result.success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result.error)
    return result
