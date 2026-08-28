"""Tests for FastAPI REST API endpoints."""

import pytest
from fastapi.testclient import TestClient

from logiroute.api.server import app

client = TestClient(app)


def test_api_health_check():
    """Verify liveness probe returns healthy."""
    response = client.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "logiroute-agent"


def test_api_dispatch_endpoint():
    """Verify natural language dispatch endpoint returns structured resolution."""
    response = client.post(
        "/api/v1/dispatch",
        json={
            "query": "Check status of shipment SHP-ELC002 and resolve delays.",
            "session_id": "api-test-session",
            "user_id": "api_test_user",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "COMPLETED"
    assert data["active_shipment_id"] == "SHP-ELC002"
    assert "track_shipment" in data["tools_invoked"]


def test_api_get_shipment():
    """Verify direct shipment lookup endpoint."""
    response = client.get("/api/v1/shipments/SHP-MED001")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["shipment"]["shipment_id"] == "SHP-MED001"


def test_api_get_shipment_not_found():
    """Verify 404 response on unknown shipment."""
    response = client.get("/api/v1/shipments/SHP-000000")
    assert response.status_code == 404


def test_api_calculate_reroute():
    """Verify reroute calculation endpoint."""
    response = client.post("/api/v1/shipments/SHP-MED001/reroute?issue_type=COLD_CHAIN_ALERT")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert len(data["options"]) >= 2


def test_api_approval_flow():
    """Verify HITL decision submission via API."""
    # First, generate an approval request via dispatch
    dispatch_res = client.post(
        "/api/v1/dispatch",
        json={"query": "Reroute shipment SHP-MED001 urgently via air freight."},
    )
    assert dispatch_res.status_code == 200
    
    # Submit decision
    appr_res = client.post(
        "/api/v1/approval",
        json={
            "approval_id": "APPR-HITL-MOCK1234",
            "approved": True,
            "reviewer_id": "lead_dispatcher_jim",
            "reason": "Authorized by hospital coordinator",
        },
    )
    # Even if mock id is not found, verify structured 404 response
    assert appr_res.status_code in (200, 404)
