import json
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.config import load_settings

from .conftest import TOKEN, _recording

KEY = "n8n-key"


def _client(settings, seen, answer):
    return TestClient(create_app(settings, _recording(seen, answer)))


@pytest.fixture
def keyed(settings):
    return replace(settings, n8n_api_key=KEY)


def test_settings_read_the_n8n_api_key():
    assert load_settings({"UIP_N8N_API_KEY": KEY}).n8n_api_key == KEY
    assert load_settings({}).n8n_api_key == ""


def test_run_posts_page_and_limit_to_the_n8n_webhook_with_the_token(settings, seen):
    with _client(settings, seen, lambda r: httpx.Response(202, json={"execution_id": "41"})) as c:
        r = c.post("/api/pipeline/run", json={"limit": 5})
    assert r.status_code == 202 and r.json() == {"execution_id": "41"}
    request = seen[-1]
    assert request.url.host == "n8n" and request.url.path == "/webhook/olivesoft-pipeline"
    assert json.loads(request.content) == {"page": 1, "limit": 5}
    assert request.headers["X-Internal-Token"] == TOKEN


def test_run_without_a_body_uses_the_defaults(client, seen):
    client.post("/api/pipeline/run")
    assert json.loads(seen[-1].content) == {"page": 1, "limit": 3}


def test_run_refuses_a_limit_over_ten_before_calling_n8n(client, seen):
    r = client.post("/api/pipeline/run", json={"limit": 11})
    assert r.status_code == 422 and seen == []


def test_an_inactive_workflow_says_how_to_activate_it(settings, seen):
    missing = {"code": 404, "message": 'The requested webhook "POST olivesoft-pipeline" is not registered.'}
    with _client(settings, seen, lambda r: httpx.Response(404, json=missing)) as c:
        r = c.post("/api/pipeline/run")
    assert r.status_code == 404 and "switch it to Active" in r.json()["error"]["message"]


def test_a_refused_webhook_names_the_credential_to_set(settings, seen):
    with _client(settings, seen, lambda r: httpx.Response(403, text="Authorization data is wrong!")) as c:
        r = c.post("/api/pipeline/run")
    assert r.status_code == 403 and "X-Internal-Token" in r.json()["error"]["message"]


def test_status_without_an_api_key_is_unavailable_and_calls_nothing(client, seen):
    r = client.get("/api/pipeline/runs/41")
    assert r.status_code == 503 and "UIP_N8N_API_KEY" in r.json()["error"]["message"]
    assert seen == []


def test_status_refuses_an_id_that_is_not_a_number(keyed, seen):
    with _client(keyed, seen, lambda r: httpx.Response(200, json={})) as c:
        assert c.get("/api/pipeline/runs/..%2Fworkflows").status_code == 404
    assert seen == []


def test_a_running_execution_is_read_once_with_the_api_key(keyed, seen):
    run = {"id": "41", "status": "running", "startedAt": "2026-10-29T10:00:00Z", "stoppedAt": None, "workflowId": "w1"}
    with _client(keyed, seen, lambda r: httpx.Response(200, json=run)) as c:
        body = c.get("/api/pipeline/runs/41").json()
    assert body == {"id": "41", "status": "running", "started_at": "2026-10-29T10:00:00Z", "stopped_at": None, "workflow_id": "w1", "error": None, "failed_node": None}
    assert len(seen) == 1 and seen[0].url.path == "/api/v1/executions/41"
    assert seen[0].headers["X-N8N-API-KEY"] == KEY and "includeData" not in str(seen[0].url)


def test_a_failed_execution_reports_its_error_and_node(keyed, seen):
    def answer(request: httpx.Request) -> httpx.Response:
        run = {"id": "41", "status": "crashed", "workflowId": "w1"}
        if request.url.params.get("includeData") == "true":
            run["data"] = {"resultData": {"error": {"message": "connect ECONNREFUSED"}, "lastNodeExecuted": "Fetch One TED Page"}}
        return httpx.Response(200, json=run)

    with _client(keyed, seen, answer) as c:
        body = c.get("/api/pipeline/runs/41").json()
    assert body["status"] == "error" and body["error"] == "connect ECONNREFUSED"
    assert body["failed_node"] == "Fetch One TED Page"


class FakeN8n:
    """Answers like n8n: the webhook works only once its node holds the .env token and the workflow is active."""

    def __init__(
        self,
        *,
        credential: dict | None,
        active: bool = True,
        stored_token: str | None = None,
        registers_after: int = 0,
        republishes_after: int = 0,
    ):
        webhook = {"type": "n8n-nodes-base.webhook", "name": "Webhook", "parameters": {"path": "olivesoft-pipeline"}}
        if credential:
            webhook["credentials"] = {"httpHeaderAuth": credential}
        self.workflow = {
            "id": "wf1",
            "name": "Phase 2",
            "active": active,
            "nodes": [webhook, {"type": "n8n-nodes-base.code", "name": "Pick Notices", "parameters": {}}],
            "connections": {"Webhook": {}},
            "settings": {"executionOrder": "v1", "binaryMode": "separate", "availableInMCP": False},
        }
        self.tokens = {credential["id"]: stored_token} if credential else {}
        self.credentials = [{"id": c["id"], "name": c["name"], "type": "httpHeaderAuth"} for c in [credential] if c]
        self.calls: list[tuple[str, str]] = []
        self.put_body: dict | None = None
        self.registers_after = registers_after
        self.republishes_after = republishes_after

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        self.calls.append((method, path))
        body = json.loads(request.content) if request.content else None
        if path == "/webhook/olivesoft-pipeline":
            if not self.workflow["active"] or self.registers_after > 0:
                self.registers_after -= self.workflow["active"]
                return httpx.Response(404, json={"code": 404, "message": "not registered"})
            attached = self.workflow["nodes"][0].get("credentials", {}).get("httpHeaderAuth")
            if self.put_body and self.republishes_after > 0:
                self.republishes_after -= 1
                attached = None
            if not attached or attached["id"] not in {c["id"] for c in self.credentials}:
                return httpx.Response(500, json={"code": 500, "message": "No authentication data defined on node!"})
            if self.tokens.get(attached["id"]) != request.headers["X-Internal-Token"]:
                return httpx.Response(403, text="Authorization data is wrong!")
            return httpx.Response(202, json={"execution_id": "7"})
        if path == "/api/v1/workflows":
            return httpx.Response(200, json={"data": [self.workflow]})
        if path == "/api/v1/credentials" and method == "GET":
            return httpx.Response(200, json={"data": self.credentials})
        if path == "/api/v1/credentials" and method == "POST":
            created = {"id": "cred-new", "name": body["name"], "type": body["type"]}
            self.credentials.append(created)
            self.tokens["cred-new"] = body["data"]["value"]
            return httpx.Response(200, json=created)
        if path.startswith("/api/v1/credentials/") and method == "PATCH":
            self.tokens[path.rsplit("/", 1)[1]] = body["data"]["value"]
            return httpx.Response(200, json={})
        if path == "/api/v1/workflows/wf1" and method == "PUT":
            self.put_body = body
            self.workflow["nodes"] = body["nodes"]
            return httpx.Response(200, json=self.workflow)
        if path == "/api/v1/workflows/wf1/activate":
            self.workflow["active"] = True
            return httpx.Response(200, json=self.workflow)
        return httpx.Response(500, json={"detail": "unexpected"})


def test_a_missing_webhook_credential_is_created_from_the_env_token_and_the_run_starts(keyed, seen):
    n8n = FakeN8n(credential=None)
    with _client(keyed, seen, n8n) as c:
        r = c.post("/api/pipeline/run")
    assert r.status_code == 202 and r.json() == {"execution_id": "7"}
    assert n8n.tokens == {"cred-new": TOKEN}
    assert n8n.put_body["nodes"][0]["credentials"] == {"httpHeaderAuth": {"id": "cred-new", "name": "OliveSoft internal token"}}
    assert set(n8n.put_body) == {"name", "nodes", "connections", "settings"}
    assert n8n.put_body["settings"] == {"executionOrder": "v1", "binaryMode": "separate"}
    assert all(r.headers["X-N8N-API-KEY"] == KEY for r in seen if r.url.path.startswith("/api/v1/"))


def test_an_existing_credential_of_the_same_name_is_reused_not_duplicated(keyed, seen):
    n8n = FakeN8n(credential=None)
    n8n.credentials.append({"id": "cred-old", "name": "OliveSoft internal token", "type": "httpHeaderAuth"})
    with _client(keyed, seen, n8n) as c:
        assert c.post("/api/pipeline/run").status_code == 202
    assert ("POST", "/api/v1/credentials") not in n8n.calls
    assert n8n.tokens == {"cred-old": TOKEN}


def test_a_refused_token_is_rewritten_from_env_in_the_attached_credential(keyed, seen):
    n8n = FakeN8n(credential={"id": "cred-1", "name": "Header Auth account"}, stored_token="stale")
    with _client(keyed, seen, n8n) as c:
        assert c.post("/api/pipeline/run").status_code == 202
    assert n8n.tokens == {"cred-1": TOKEN}
    assert ("PUT", "/api/v1/workflows/wf1") not in n8n.calls


def test_an_unpublished_workflow_is_activated_and_the_run_starts(keyed, seen):
    n8n = FakeN8n(credential={"id": "cred-1", "name": "Header Auth account"}, stored_token=TOKEN, active=False)
    with _client(keyed, seen, n8n) as c:
        assert c.post("/api/pipeline/run").status_code == 202
    assert ("POST", "/api/v1/workflows/wf1/activate") in n8n.calls
    assert n8n.calls.count(("POST", "/webhook/olivesoft-pipeline")) == 2


def test_without_an_api_key_nothing_in_n8n_is_touched(settings, seen):
    n8n = FakeN8n(credential=None)
    with _client(settings, seen, n8n) as c:
        r = c.post("/api/pipeline/run")
    assert r.status_code == 503 and "UIP_N8N_API_KEY" in r.json()["error"]["message"]
    assert n8n.calls == [("POST", "/webhook/olivesoft-pipeline")]


def test_when_no_workflow_holds_the_webhook_the_refusal_is_shown_without_a_retry(keyed, seen):
    n8n = FakeN8n(credential=None, active=False)
    n8n.workflow["nodes"] = n8n.workflow["nodes"][1:]
    with _client(keyed, seen, n8n) as c:
        r = c.post("/api/pipeline/run")
    assert r.status_code == 404 and "switch it to Active" in r.json()["error"]["message"]
    assert n8n.calls.count(("POST", "/webhook/olivesoft-pipeline")) == 1


def test_a_failure_with_nothing_to_repair_is_not_retried(keyed, seen):
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with _client(keyed, seen, down) as c:
        r = c.post("/api/pipeline/run")
    assert r.status_code == 503 and "could not be reached" in r.json()["error"]["message"]
    assert [x.url.path for x in seen] == ["/webhook/olivesoft-pipeline", "/api/v1/workflows"]


def test_a_just_published_webhook_is_retried_until_n8n_registers_it(keyed, seen, monkeypatch):
    waits = []
    monkeypatch.setattr("server.app.time.sleep", waits.append)
    n8n = FakeN8n(credential=None, active=False, registers_after=2)
    with _client(keyed, seen, n8n) as c:
        assert c.post("/api/pipeline/run").status_code == 202
    assert n8n.calls.count(("POST", "/webhook/olivesoft-pipeline")) == 4
    assert waits == [1.0, 1.0]


def test_the_retries_stop_after_five_tries(keyed, seen, monkeypatch):
    monkeypatch.setattr("server.app.time.sleep", lambda s: None)
    n8n = FakeN8n(credential=None, active=False, registers_after=99)
    with _client(keyed, seen, n8n) as c:
        assert c.post("/api/pipeline/run").status_code == 404
    assert n8n.calls.count(("POST", "/webhook/olivesoft-pipeline")) == 6


def test_a_credential_id_this_n8n_does_not_have_is_replaced(keyed, seen):
    n8n = FakeN8n(credential={"id": "cred-gone", "name": "Header Auth account"}, stored_token=TOKEN)
    n8n.credentials = []
    with _client(keyed, seen, n8n) as c:
        assert c.post("/api/pipeline/run").status_code == 202
    assert n8n.put_body["nodes"][0]["credentials"]["httpHeaderAuth"]["id"] == "cred-new"
    assert n8n.tokens["cred-new"] == TOKEN


def test_a_republished_webhook_still_on_its_old_credential_is_retried(keyed, seen, monkeypatch):
    monkeypatch.setattr("server.app.time.sleep", lambda s: None)
    n8n = FakeN8n(credential=None, republishes_after=2)
    with _client(keyed, seen, n8n) as c:
        assert c.post("/api/pipeline/run").status_code == 202
    assert n8n.calls.count(("POST", "/webhook/olivesoft-pipeline")) == 4
