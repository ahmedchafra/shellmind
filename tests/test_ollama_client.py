from __future__ import annotations

from typing import Any

import shellmind.llm.ollama_client as client_module


class FakeClient:
    cloud_available = True
    created_hosts: list[str] = []

    def __init__(
        self,
        host: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.host = host
        self.headers = headers
        self.created_hosts.append(host)

    def show(self, model: str) -> dict[str, Any]:
        if self.host == "https://ollama.com" and not self.cloud_available:
            raise RuntimeError("cloud unavailable")
        return {"model": model}

    def ps(self) -> dict[str, Any]:
        return {}

    def chat(self, model: str, messages: list[dict[str, str]], stream: bool = False) -> Any:
        return {"message": {"content": "ok"}}


def test_default_mode_prefers_cloud_when_key_and_model_are_available(monkeypatch) -> None:
    FakeClient.cloud_available = True
    FakeClient.created_hosts = []
    monkeypatch.setattr(client_module, "Client", FakeClient)
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")

    client = client_module.OllamaClientWrapper(cloud_models=["cloud-model"])

    assert client.active_mode == "cloud"
    assert client.active_model == "cloud-model"
    assert "https://ollama.com" in FakeClient.created_hosts


def test_cloud_failure_falls_back_to_local(monkeypatch) -> None:
    FakeClient.cloud_available = False
    FakeClient.created_hosts = []
    monkeypatch.setattr(client_module, "Client", FakeClient)
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")

    client = client_module.OllamaClientWrapper(
        cloud_models=["unavailable-cloud-model"],
        local_model="local-model",
    )

    assert client.active_mode == "local"
    assert client.active_model == "local-model"


def test_missing_cloud_key_falls_back_to_local(monkeypatch) -> None:
    FakeClient.cloud_available = True
    FakeClient.created_hosts = []
    monkeypatch.setattr(client_module, "Client", FakeClient)
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)

    client = client_module.OllamaClientWrapper(local_model="local-model")

    assert client.active_mode == "local"
    assert client.active_model == "local-model"
