from pathlib import Path

import yaml

from server.config import load_settings

REPO = Path(__file__).resolve().parents[3]


def test_health_needs_no_token(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_no_response_ever_contains_the_token(client):
    for path in ("/health", "/api/health", "/"):
        assert "dev-token" not in client.get(path).text


def test_health_reports_each_service(client_with_rag_down):
    rows = {r["id"]: r for r in client_with_rag_down.get("/api/health").json()}
    assert rows["detection"]["up"] is True and rows["rag"]["up"] is False
    assert rows["rag"]["status"] is None and rows["detection"]["status"] == 200


def test_health_covers_every_service_without_a_token(client, seen):
    rows = client.get("/api/health").json()
    assert [r["id"] for r in rows] == ["detection", "rag", "research", "proposal",
                                       "insights", "ingestion", "n8n"]
    assert all("X-Internal-Token" not in r.headers for r in seen)
    assert {r.url.path for r in seen if r.url.host == "n8n"} == {"/healthz"}


def test_error_envelope_and_request_id_echo(client):
    r = client.get("/src/does-not-exist.js", headers={"X-Request-ID": "req-1"})
    assert r.status_code == 404
    assert r.headers["X-Request-ID"] == "req-1"
    assert r.json()["error"]["code"] == "NOT_FOUND" and r.json()["error"]["request_id"] == "req-1"


def test_static_root_and_folders(client):
    index = client.get("/")
    assert index.status_code == 200 and "<title>" in index.text
    assert client.get("/src/app.js").status_code == 200
    assert client.get("/vendor/final/tokens.css").status_code == 200


def test_server_code_is_not_served(client):
    for path in ("/server/app.py", "/src/../server/app.py", "/scripts", "/tests"):
        assert client.get(path).status_code == 404


def test_load_settings_defaults_to_localhost():
    s = load_settings({})
    assert s.token == "" and s.services["detection"] == "http://localhost:8000"
    assert s.services["n8n"] == "http://localhost:5678"
    assert s.timeouts == {"default": 30, "research": 150, "deck": 180, "ingest": 60,
                          "insights": 160}
    assert s.services["insights"] == "http://localhost:8006"


def test_load_settings_reads_the_environment():
    s = load_settings({"INTERNAL_SERVICE_TOKEN": "t", "UIP_RAG_URL": "http://rag:8001/"})
    assert s.token == "t" and s.services["rag"] == "http://rag:8001"


def test_compose_defines_the_ui_service():
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text())["services"]
    ui = compose["ui"]
    assert ui["ports"] == ["127.0.0.1:8005:8005"]
    # the only mount is the read-only sources mount for live reload,
    # never a data volume: the ui owns nothing.
    assert ui["volumes"] == ["./ui-preview:/app/ui-preview:ro"]
    assert ui["environment"]["UIP_RAG_URL"] == "http://rag:8001"
    assert ui["environment"]["UIP_N8N_URL"] == "http://n8n:5678"
    assert ui["environment"]["UIP_INSIGHTS_URL"] == "http://insights:8006"
