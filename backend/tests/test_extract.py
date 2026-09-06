import json

import httpx
from fastapi.testclient import TestClient

COMPLETE_MODEL = {
    "city_a": "杭州",
    "address_a": "杭州东站",
    "city_b": "杭州",
    "address_b": "西湖龙翔桥地铁站",
    "category": "咖啡店",
    "party_count": 2,
    "incomplete_reason": None,
}


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


def _settings(**overrides):
    values = {
        "deepseek_api_key": "sk-test",
        "deepseek_url": "https://api.deepseek.com/chat/completions",
        "deepseek_model": "deepseek-v4-flash",
        "extract_timeout_seconds": 15.0,
        "extract_max_tokens": 1024,
    }
    values.update(overrides)
    return type("S", (), values)()


def _patch_upstream(monkeypatch, fake: _FakeClient, settings=None) -> None:
    monkeypatch.setattr("services.extract.httpx.AsyncClient", lambda timeout=None: fake)
    monkeypatch.setattr("services.extract.get_settings", lambda: settings or _settings())


def _choice(content: object, finish_reason: str = "stop") -> dict:
    return {
        "choices": [
            {
                "finish_reason": finish_reason,
                "message": {"content": content},
            }
        ]
    }


def test_extract_success_returns_five_business_fields(
    client: TestClient, monkeypatch
) -> None:
    fake = _FakeClient(_FakeResponse(_choice(json.dumps(COMPLETE_MODEL))))
    _patch_upstream(monkeypatch, fake)

    response = client.post(
        "/extract",
        json={
            "text": "我在杭州东站，朋友在西湖龙翔桥地铁站，帮我们找个中间的咖啡店。",
            "city": "杭州",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["request_id"]
    assert body["data"] == {
        "city_a": "杭州",
        "address_a": "杭州东站",
        "city_b": "杭州",
        "address_b": "西湖龙翔桥地铁站",
        "category": "咖啡店",
    }
    assert "party_count" not in body["data"]
    assert "incomplete_reason" not in body["data"]
    sent = fake.calls[0]
    assert sent["url"] == "https://api.deepseek.com/chat/completions"
    assert sent["json"]["model"] == "deepseek-v4-flash"
    assert sent["json"]["thinking"] == {"type": "disabled"}
    assert sent["json"]["response_format"] == {"type": "json_object"}
    assert "json" in sent["json"]["messages"][0]["content"].lower()
    assert "页面城市：杭州" in sent["json"]["messages"][1]["content"]
    assert "sk-test" not in str(body)


def test_extract_uses_page_city_when_model_city_is_null(
    client: TestClient, monkeypatch
) -> None:
    payload = {
        **COMPLETE_MODEL,
        "city_a": None,
        "city_b": None,
        "incomplete_reason": None,
    }
    fake = _FakeClient(_FakeResponse(_choice(json.dumps(payload))))
    _patch_upstream(monkeypatch, fake)
    response = client.post(
        "/extract",
        json={"text": "我在东站，朋友在西湖龙翔桥地铁站，找个咖啡店。", "city": "杭州"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["city_a"] == "杭州"
    assert response.json()["data"]["city_b"] == "杭州"


def test_extract_keeps_spoken_city_over_page_city(
    client: TestClient, monkeypatch
) -> None:
    payload = {
        **COMPLETE_MODEL,
        "city_a": "宁波",
        "address_a": "宁波火车站",
        "city_b": "宁波",
        "address_b": "天一广场",
    }
    fake = _FakeClient(_FakeResponse(_choice(json.dumps(payload))))
    _patch_upstream(monkeypatch, fake)
    response = client.post(
        "/extract",
        json={
            "text": "我在宁波火车站，朋友在天一广场，帮我们找个中间的咖啡店。",
            "city": "杭州",
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["city_a"] == "宁波"
    assert data["city_b"] == "宁波"


def test_extract_defaults_missing_category(client: TestClient, monkeypatch) -> None:
    payload = {**COMPLETE_MODEL, "category": None}
    fake = _FakeClient(_FakeResponse(_choice(json.dumps(payload))))
    _patch_upstream(monkeypatch, fake)
    response = client.post(
        "/extract",
        json={
            "text": "我在杭州东站，朋友在西湖龙翔桥地铁站，帮我们找个中间碰面的地方。",
            "city": "杭州",
        },
    )
    assert response.status_code == 200
    assert response.json()["data"]["category"] == "咖啡店"


def test_extract_null_party_count_is_invalid(client: TestClient, monkeypatch) -> None:
    payload = {**COMPLETE_MODEL, "party_count": None, "incomplete_reason": "人数说不清"}
    fake = _FakeClient(_FakeResponse(_choice(json.dumps(payload))))
    _patch_upstream(monkeypatch, fake)
    response = client.post(
        "/extract",
        json={"text": "杭州东站和龙翔桥中间找个咖啡店。", "city": "杭州"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PARTY_COUNT_INVALID"


def test_extract_wrong_party_count_type_is_model_error(
    client: TestClient, monkeypatch
) -> None:
    payload = {**COMPLETE_MODEL, "party_count": "两人"}
    fake = _FakeClient(_FakeResponse(_choice(json.dumps(payload))))
    _patch_upstream(monkeypatch, fake)
    response = client.post(
        "/extract",
        json={"text": "我在杭州东站，朋友在龙翔桥。", "city": "杭州"},
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "MODEL_OUTPUT_INVALID"


def test_extract_normalizes_category(client: TestClient, monkeypatch) -> None:
    payload = {**COMPLETE_MODEL, "category": "喝咖啡"}
    fake = _FakeClient(_FakeResponse(_choice(json.dumps(payload))))
    _patch_upstream(monkeypatch, fake)
    response = client.post(
        "/extract",
        json={
            "text": "我在杭州东站，朋友在西湖龙翔桥地铁站，帮我们找个中间喝咖啡的地方。",
            "city": "杭州",
        },
    )
    assert response.status_code == 200
    assert response.json()["data"]["category"] == "咖啡店"


def test_extract_same_city_after_stripping_shi(client: TestClient, monkeypatch) -> None:
    payload = {**COMPLETE_MODEL, "city_a": "杭州", "city_b": "杭州市"}
    fake = _FakeClient(_FakeResponse(_choice(json.dumps(payload))))
    _patch_upstream(monkeypatch, fake)
    response = client.post(
        "/extract",
        json={
            "text": "我在杭州东站，朋友在杭州市西湖龙翔桥地铁站，找个咖啡店。",
            "city": "杭州",
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["city_a"] == "杭州"
    assert data["city_b"] == "杭州"


def test_extract_missing_address_is_incomplete(client: TestClient, monkeypatch) -> None:
    payload = {
        **COMPLETE_MODEL,
        "address_a": None,
        "incomplete_reason": "缺少一方具体地址",
    }
    fake = _FakeClient(_FakeResponse(_choice(json.dumps(payload))))
    _patch_upstream(monkeypatch, fake)
    response = client.post(
        "/extract",
        json={"text": "我在杭州东站，帮我们找个中间的咖啡店。", "city": "杭州"},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "EXTRACT_INCOMPLETE"
    assert body["error"]["stage"] == "extract"
    assert "data" not in body


def test_extract_vague_home_is_incomplete(client: TestClient, monkeypatch) -> None:
    payload = {
        **COMPLETE_MODEL,
        "address_a": None,
        "incomplete_reason": "一方地点含糊，无法确定具体地址",
    }
    fake = _FakeClient(_FakeResponse(_choice(json.dumps(payload))))
    _patch_upstream(monkeypatch, fake)
    response = client.post(
        "/extract",
        json={
            "text": "我在我家，朋友在西湖龙翔桥地铁站，帮我们找个中间的咖啡店。",
            "city": "杭州",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EXTRACT_INCOMPLETE"


def test_extract_party_count_invalid(client: TestClient, monkeypatch) -> None:
    payload = {
        **COMPLETE_MODEL,
        "city_b": None,
        "address_b": None,
        "party_count": 3,
        "incomplete_reason": "人数不是两人",
    }
    fake = _FakeClient(_FakeResponse(_choice(json.dumps(payload))))
    _patch_upstream(monkeypatch, fake)
    response = client.post(
        "/extract",
        json={
            "text": "我在杭州东站，小李在龙翔桥，小王在城西银泰，帮我们三个人找个咖啡店。",
            "city": "杭州",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PARTY_COUNT_INVALID"


def test_extract_cross_city(client: TestClient, monkeypatch) -> None:
    payload = {
        **COMPLETE_MODEL,
        "city_b": "宁波",
        "address_b": "宁波火车站",
        "incomplete_reason": "两人不在同一座城市",
    }
    fake = _FakeClient(_FakeResponse(_choice(json.dumps(payload))))
    _patch_upstream(monkeypatch, fake)
    response = client.post(
        "/extract",
        json={
            "text": "我在杭州东站，朋友在宁波火车站，帮我们找个中间的咖啡店。",
            "city": "杭州",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CROSS_CITY"


def test_extract_invalid_json_is_model_error(client: TestClient, monkeypatch) -> None:
    fake = _FakeClient(_FakeResponse(_choice("not-json")))
    _patch_upstream(monkeypatch, fake)
    response = client.post(
        "/extract",
        json={"text": "我在杭州东站，朋友在龙翔桥。", "city": "杭州"},
    )
    assert response.status_code == 502
    body = response.json()
    assert body["error"]["code"] == "MODEL_OUTPUT_INVALID"
    assert body["error"]["stage"] == "extract"


def test_extract_missing_model_field_is_model_error(
    client: TestClient, monkeypatch
) -> None:
    payload = dict(COMPLETE_MODEL)
    del payload["party_count"]
    fake = _FakeClient(_FakeResponse(_choice(json.dumps(payload))))
    _patch_upstream(monkeypatch, fake)
    response = client.post(
        "/extract",
        json={"text": "我在杭州东站，朋友在龙翔桥。", "city": "杭州"},
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "MODEL_OUTPUT_INVALID"


def test_extract_empty_content_is_model_error(client: TestClient, monkeypatch) -> None:
    fake = _FakeClient(_FakeResponse(_choice("   ")))
    _patch_upstream(monkeypatch, fake)
    response = client.post(
        "/extract",
        json={"text": "我在杭州东站，朋友在龙翔桥。", "city": "杭州"},
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "MODEL_OUTPUT_INVALID"


def test_extract_truncated_output_is_model_error(
    client: TestClient, monkeypatch
) -> None:
    fake = _FakeClient(
        _FakeResponse(_choice(json.dumps(COMPLETE_MODEL), finish_reason="length"))
    )
    _patch_upstream(monkeypatch, fake)
    response = client.post(
        "/extract",
        json={"text": "我在杭州东站，朋友在龙翔桥。", "city": "杭州"},
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "MODEL_OUTPUT_INVALID"


def test_extract_missing_text_returns_422(client: TestClient) -> None:
    response = client.post("/extract", json={"city": "杭州"})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["stage"] == "extract"


def test_extract_timeout_returns_504(client: TestClient, monkeypatch) -> None:
    fake = _FakeClient(error=httpx.TimeoutException("timeout"))
    _patch_upstream(monkeypatch, fake)
    response = client.post(
        "/extract",
        json={"text": "我在杭州东站，朋友在龙翔桥。", "city": "杭州"},
    )
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "UPSTREAM_TIMEOUT"
    assert response.json()["error"]["stage"] == "extract"


def test_extract_upstream_error_returns_502(client: TestClient, monkeypatch) -> None:
    fake = _FakeClient(_FakeResponse({"error": {"message": "fail"}}, status_code=500))
    _patch_upstream(monkeypatch, fake)
    response = client.post(
        "/extract",
        json={"text": "我在杭州东站，朋友在龙翔桥。", "city": "杭州"},
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_ERROR"


def test_extract_missing_key_returns_502(client: TestClient, monkeypatch) -> None:
    fake = _FakeClient(_FakeResponse(_choice(json.dumps(COMPLETE_MODEL))))
    _patch_upstream(monkeypatch, fake, settings=_settings(deepseek_api_key=""))
    response = client.post(
        "/extract",
        json={"text": "我在杭州东站，朋友在龙翔桥。", "city": "杭州"},
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_ERROR"
    assert fake.calls == []
