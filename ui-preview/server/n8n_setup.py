"""Puts the pipeline webhook back in working order from .env: its Header Auth credential and its published state."""

from typing import Any

from .config import Settings
from .upstream import TOKEN_HEADER, Upstream

WEBHOOK_PATH = "olivesoft-pipeline"
CREDENTIAL_TYPE = "httpHeaderAuth"
CREDENTIAL_NAME = "OliveSoft internal token"
# The only settings n8n's public API accepts on a workflow update; anything else is refused.
WORKFLOW_SETTINGS = {
    "saveExecutionProgress",
    "saveManualExecutions",
    "saveDataErrorExecution",
    "saveDataSuccessExecution",
    "executionTimeout",
    "errorWorkflow",
    "timezone",
    "executionOrder",
    "binaryMode",
    "callerPolicy",
    "callerIds",
    "timeSavedMode",
    "timeSavedPerExecution",
}


def _is_pipeline_webhook(node: dict) -> bool:
    return node.get("type") == "n8n-nodes-base.webhook" and node.get("parameters", {}).get("path") == WEBHOOK_PATH


def repair_pipeline_webhook(upstream: Upstream, settings: Settings, *, token_refused: bool) -> bool:
    """Gives the webhook a credential holding INTERNAL_SERVICE_TOKEN and publishes its workflow.

    Returns True when something changed, so calling the webhook again is worth it.
    """
    headers = {"X-N8N-API-KEY": settings.n8n_api_key}

    def api(method: str, path: str, json: Any = None) -> Any:
        return upstream.call("n8n", method, "/api/v1" + path, json=json, headers=headers)[1]

    workflow = next(
        (w for w in api("GET", "/workflows?limit=250")["data"] if any(map(_is_pipeline_webhook, w["nodes"]))),
        None,
    )
    if workflow is None:
        return False
    node = next(filter(_is_pipeline_webhook, workflow["nodes"]))
    known = [c for c in api("GET", "/credentials?limit=250")["data"] if c["type"] == CREDENTIAL_TYPE]
    attached = (node.get("credentials") or {}).get(CREDENTIAL_TYPE)
    # A workflow imported from another n8n, or whose credential was deleted, points at an id this n8n lacks.
    if attached and attached.get("id") not in {c["id"] for c in known}:
        attached = None
    changed = False

    if attached is None or token_refused:
        data = {"name": TOKEN_HEADER, "value": settings.token}
        credential = attached or next((c for c in known if c["name"] == CREDENTIAL_NAME), None)
        if credential:
            api("PATCH", f"/credentials/{credential['id']}", {"data": data})
        else:
            credential = api("POST", "/credentials", {"name": CREDENTIAL_NAME, "type": CREDENTIAL_TYPE, "data": data})
        changed = True

    if attached is None:
        node["credentials"] = {CREDENTIAL_TYPE: {"id": credential["id"], "name": credential["name"]}}
        api(
            "PUT",
            f"/workflows/{workflow['id']}",
            {
                "name": workflow["name"],
                "nodes": workflow["nodes"],
                "connections": workflow["connections"],
                "settings": {k: v for k, v in (workflow.get("settings") or {}).items() if k in WORKFLOW_SETTINGS},
            },
        )

    if not workflow.get("active"):
        api("POST", f"/workflows/{workflow['id']}/activate")
        changed = True
    return changed
