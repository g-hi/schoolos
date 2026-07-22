from fastapi.testclient import TestClient
from services.gateway.main import app


def test_demo_bootstrap_endpoints_not_in_openapi():
    client = TestClient(app)
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    data = resp.json()
    paths = data.get("paths", {})
    assert "/internal/demo-bootstrap/status" not in paths
    assert "/internal/demo-bootstrap/apply" not in paths
