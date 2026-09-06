import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

AUDIO_ID = "aud_" + ("a" * 32)


def _seed_audio(
    tmp_path: Path,
    audio_id: str = AUDIO_ID,
    created_at: datetime | None = None,
    data: bytes = b"fake-webm-bytes",
) -> None:
    created = created_at or datetime.now(timezone.utc)
    (tmp_path / f"{audio_id}.webm").write_bytes(data)
    (tmp_path / f"{audio_id}.json").write_text(
        json.dumps(
            {
                "audio_id": audio_id,
                "created_at": created.isoformat(),
                "filename": f"{audio_id}.webm",
                "mime_type": "audio/webm",
                "size_bytes": len(data),
                "container": "matroska,webm",
                "codec": "opus",
                "duration_seconds": 3.2,
                "duration_source": "packets",
            }
        ),
        encoding="utf-8",
    )


def _patch_storage(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "services.audio_store.audio_storage_dir",
        lambda settings=None: tmp_path,
    )


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error
        self.calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, headers=None, json=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        if self._error:
            raise self._error
        return self._response


def test_asr_success_returns_vendor_text(
    client: TestClient, monkeypatch, tmp_path: Path
) -> None:
    _patch_storage(monkeypatch, tmp_path)
    _seed_audio(tmp_path)
    fake = _FakeClient(
        _FakeResponse(
            {"choices": [{"message": {"content": "我在杭州东站，朋友在西湖龙翔桥地铁站。"}}]}
        )
    )
    monkeypatch.setattr("services.asr.httpx.AsyncClient", lambda timeout=None: fake)
    monkeypatch.setattr(
        "services.asr.get_settings",
        lambda: type(
            "S",
            (),
            {
                "bailian_api_key": "sk-test",
                "bailian_asr_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                "bailian_asr_model": "qwen3-asr-flash",
                "asr_timeout_seconds": 20.0,
                "max_asr_base64_bytes": 10 * 1024 * 1024,
            },
        )(),
    )

    response = client.post("/asr", json={"audio_id": AUDIO_ID})

    assert response.status_code == 200
    body = response.json()
    assert body["request_id"]
    assert body["data"]["text"] == "我在杭州东站，朋友在西湖龙翔桥地铁站。"
    sent = fake.calls[0]
    assert sent["url"].endswith("/compatible-mode/v1/chat/completions")
    assert sent["json"]["model"] == "qwen3-asr-flash"
    data_url = sent["json"]["messages"][0]["content"][0]["input_audio"]["data"]
    assert data_url.startswith("data:audio/webm;base64,")
    assert "sk-test" not in str(response.json())


def test_asr_missing_audio_id(client: TestClient) -> None:
    response = client.post("/asr", json={})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["stage"] == "asr"


def test_asr_unknown_id_returns_404(client: TestClient, monkeypatch, tmp_path: Path) -> None:
    _patch_storage(monkeypatch, tmp_path)
    response = client.post("/asr", json={"audio_id": "aud_" + ("b" * 32)})
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "AUDIO_NOT_FOUND"
    assert body["error"]["stage"] == "asr"


def test_asr_expired_id_returns_404(client: TestClient, monkeypatch, tmp_path: Path) -> None:
    _patch_storage(monkeypatch, tmp_path)
    _seed_audio(
        tmp_path,
        created_at=datetime.now(timezone.utc) - timedelta(hours=25),
    )
    response = client.post("/asr", json={"audio_id": AUDIO_ID})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "AUDIO_NOT_FOUND"


def test_asr_empty_text_returns_422(
    client: TestClient, monkeypatch, tmp_path: Path
) -> None:
    _patch_storage(monkeypatch, tmp_path)
    _seed_audio(tmp_path)
    fake = _FakeClient(_FakeResponse({"choices": [{"message": {"content": "   "}}]}))
    monkeypatch.setattr("services.asr.httpx.AsyncClient", lambda timeout=None: fake)
    monkeypatch.setattr(
        "services.asr.get_settings",
        lambda: type(
            "S",
            (),
            {
                "bailian_api_key": "sk-test",
                "bailian_asr_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                "bailian_asr_model": "qwen3-asr-flash",
                "asr_timeout_seconds": 20.0,
                "max_asr_base64_bytes": 10 * 1024 * 1024,
            },
        )(),
    )
    response = client.post("/asr", json={"audio_id": AUDIO_ID})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ASR_EMPTY"


def test_asr_timeout_returns_504(client: TestClient, monkeypatch, tmp_path: Path) -> None:
    _patch_storage(monkeypatch, tmp_path)
    _seed_audio(tmp_path)
    fake = _FakeClient(error=httpx.TimeoutException("timeout"))
    monkeypatch.setattr("services.asr.httpx.AsyncClient", lambda timeout=None: fake)
    monkeypatch.setattr(
        "services.asr.get_settings",
        lambda: type(
            "S",
            (),
            {
                "bailian_api_key": "sk-test",
                "bailian_asr_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                "bailian_asr_model": "qwen3-asr-flash",
                "asr_timeout_seconds": 20.0,
                "max_asr_base64_bytes": 10 * 1024 * 1024,
            },
        )(),
    )
    response = client.post("/asr", json={"audio_id": AUDIO_ID})
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "UPSTREAM_TIMEOUT"
    assert response.json()["error"]["stage"] == "asr"


def test_asr_upstream_error_returns_502(
    client: TestClient, monkeypatch, tmp_path: Path
) -> None:
    _patch_storage(monkeypatch, tmp_path)
    _seed_audio(tmp_path)
    fake = _FakeClient(_FakeResponse({"error": {"message": "fail"}}, status_code=500))
    monkeypatch.setattr("services.asr.httpx.AsyncClient", lambda timeout=None: fake)
    monkeypatch.setattr(
        "services.asr.get_settings",
        lambda: type(
            "S",
            (),
            {
                "bailian_api_key": "sk-test",
                "bailian_asr_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                "bailian_asr_model": "qwen3-asr-flash",
                "asr_timeout_seconds": 20.0,
                "max_asr_base64_bytes": 10 * 1024 * 1024,
            },
        )(),
    )
    response = client.post("/asr", json={"audio_id": AUDIO_ID})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_ERROR"


def test_asr_encoded_size_too_large(
    client: TestClient, monkeypatch, tmp_path: Path
) -> None:
    _patch_storage(monkeypatch, tmp_path)
    _seed_audio(tmp_path, data=b"abcdefgh")
    monkeypatch.setattr(
        "services.asr.get_settings",
        lambda: type(
            "S",
            (),
            {
                "bailian_api_key": "sk-test",
                "bailian_asr_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                "bailian_asr_model": "qwen3-asr-flash",
                "asr_timeout_seconds": 20.0,
                "max_asr_base64_bytes": 4,
            },
        )(),
    )
    response = client.post("/asr", json={"audio_id": AUDIO_ID})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "AUDIO_TOO_LARGE"
    assert response.json()["error"]["stage"] == "asr"
