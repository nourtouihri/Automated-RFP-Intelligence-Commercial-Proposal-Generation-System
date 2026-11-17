import os
from dataclasses import dataclass
from typing import Mapping

_SERVICE_PORTS = {
    "detection": 8000,
    "rag": 8001,
    "research": 8002,
    "proposal": 8003,
    "insights": 8006,
    "ingestion": 8004,
    "n8n": 5678,
}

_TIMEOUTS = {"default": 30.0, "research": 150.0, "deck": 180.0, "ingest": 60.0,
             "insights": 160.0}


@dataclass(frozen=True)
class Settings:
    token: str
    services: dict[str, str]
    timeouts: dict[str, float]
    n8n_api_key: str = ""


def load_settings(env: Mapping[str, str] = os.environ) -> Settings:
    services = {
        name: env.get(f"UIP_{name.upper()}_URL", f"http://localhost:{port}").rstrip("/")
        for name, port in _SERVICE_PORTS.items()
    }
    return Settings(
        token=env.get("INTERNAL_SERVICE_TOKEN", ""),
        services=services,
        timeouts=dict(_TIMEOUTS),
        n8n_api_key=env.get("UIP_N8N_API_KEY", ""),
    )
