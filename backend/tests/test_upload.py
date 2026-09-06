from pathlib import Path

from fastapi.testclient import TestClient

from services.audio_probe import ProbeResult


def _patch_storage(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "services.audio_store.audio_storage_dir",
        lambda settings=None: tmp_path,
    )


def test_upload_success_returns_audio_id(client: TestClient, monkeypatch, tmp_path: Path) -> None:
    _patch_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "api.upload.probe_audio_file",
        lambda path, settings=None: ProbeResult(
            container="matroska,webm",
            codec="opus",
            duration_seconds=3.2,
            duration_source="packets",
        ),
    )

    response = client.post(
        "/upload",
        files={"file": ("meetup-recording.webm", b"fake-webm-bytes", "audio/webm")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["request_id"]
    audio_id = body["data"]["audio_id"]
    assert audio_id.startswith("aud_")
    assert "/" not in audio_id
    assert "\\" not in audio_id
    assert (tmp_path / f"{audio_id}.webm").read_bytes() == b"fake-webm-bytes"
    metadata = (tmp_path / f"{audio_id}.json").read_text(encoding="utf-8")
    assert "created_at" in metadata


def test_upload_rejects_missing_file(client: TestClient) -> None:
    response = client.post("/upload")
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["stage"] == "upload"
    assert body["error"]["message"]


def test_upload_rejects_oversize_file(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "api.upload.probe_audio_file",
        lambda path, settings=None: (_ for _ in ()).throw(AssertionError("should not probe")),
    )
    payload = b"x" * (5 * 1024 * 1024 + 1)
    response = client.post(
        "/upload",
        files={"file": ("too-big.webm", payload, "audio/webm")},
    )
    assert response.status_code == 413
    body = response.json()
    assert body["error"] == {
        "code": "AUDIO_TOO_LARGE",
        "message": "录音文件过大，请控制在 5MB 以内。",
        "stage": "upload",
    }


def test_upload_rejects_unsupported_format(client: TestClient, monkeypatch, tmp_path: Path) -> None:
    _patch_storage(monkeypatch, tmp_path)
    from api.errors import AppError

    def fake_probe(path, settings=None):
        raise AppError(
            415,
            "AUDIO_UNSUPPORTED",
            "录音格式不受支持，请使用 WebM/Opus。",
            "upload",
        )

    monkeypatch.setattr("api.upload.probe_audio_file", fake_probe)
    response = client.post(
        "/upload",
        files={"file": ("clip.mp3", b"id3-fake", "audio/mpeg")},
    )
    assert response.status_code == 415
    body = response.json()
    assert body["error"]["code"] == "AUDIO_UNSUPPORTED"
    assert body["error"]["stage"] == "upload"


def test_upload_rejects_invalid_duration(client: TestClient, monkeypatch, tmp_path: Path) -> None:
    _patch_storage(monkeypatch, tmp_path)
    from api.errors import AppError

    def fake_probe(path, settings=None):
        raise AppError(
            422,
            "AUDIO_DURATION_INVALID",
            "录音时长需要在 1 到 60 秒之间。",
            "upload",
        )

    monkeypatch.setattr("api.upload.probe_audio_file", fake_probe)
    response = client.post(
        "/upload",
        files={"file": ("short.webm", b"fake-webm-bytes", "audio/webm")},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "AUDIO_DURATION_INVALID"
    assert body["error"]["stage"] == "upload"
