"""Explicit, small real model calls from the native settings dialog; never save credentials."""

import json
import math
import time

import httpx
from cairn_api.knowledge.answer_protocols import (
    AnswerProtocolError,
    build_answer_request,
    extract_answer_text,
)

from cairn_desktop.models import (
    EmbeddingConnection,
    ModelConnection,
    ModelSettingsError,
    prepare_model_update,
)

PROBE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["ok"],
    "properties": {"ok": {"type": "boolean"}},
}


def probe_connection(connection: ModelConnection, *, client: httpx.Client | None = None) -> dict:
    owned = client is None
    client = client or httpx.Client(timeout=20.0, follow_redirects=False, trust_env=False)
    connected = False
    try:
        if isinstance(connection, EmbeddingConnection):
            endpoint = str(connection.base_url).rstrip("/") + "/embeddings"
            headers = {"Authorization": "Bearer " + connection.api_key.get_secret_value()}
            body = {"model": connection.model, "input": ["Cairn 连通性测试"], "dimensions": 1024}
        else:
            request = build_answer_request(
                protocol=connection.protocol,
                base_url=str(connection.base_url),
                api_key=connection.api_key.get_secret_value(),
                model=connection.model,
                system_prompt='Return only the JSON object {"ok":true}.',
                user_content="Cairn model connection test",
                answer_schema=PROBE_SCHEMA,
                max_output_tokens=128,
            )
            endpoint, headers, body = request.endpoint, request.headers, request.body
        started = time.monotonic()
        with client.stream("POST", endpoint, headers=headers, json=body) as response:
            connected = True
            if response.status_code != 200:
                hints = {
                    401: "请检查 API Key",
                    403: "请检查模型使用权限",
                    404: "请检查协议、服务基础地址和模型名",
                    429: "请检查额度或请求频率",
                }
                return {
                    "connected": True,
                    "callSucceeded": False,
                    "message": f"服务已响应，调用失败（HTTP {response.status_code}）；"
                    + hints.get(response.status_code, "请检查服务状态")
                    + "。",
                }
            raw = bytearray()
            for chunk in response.iter_bytes():
                if len(raw) + len(chunk) > 256 * 1024 or time.monotonic() - started > 20:
                    return {
                        "connected": True,
                        "callSucceeded": False,
                        "message": "服务已响应，但返回内容过大或超时。",
                    }
                raw.extend(chunk)
        payload = json.loads(raw)
        if isinstance(connection, EmbeddingConnection):
            data = payload["data"]
            vector = data[0]["embedding"]
            valid = (
                len(data) == 1
                and data[0]["index"] == 0
                and len(vector) == 1024
                and all(type(v) in (int, float) and math.isfinite(v) for v in vector)
            )
        else:
            text = extract_answer_text(protocol=connection.protocol, payload=payload)
            decoded = json.loads(text)
            valid = isinstance(decoded, dict) and set(decoded) == {"ok"} and decoded["ok"] is True
        return {
            "connected": True,
            "callSucceeded": valid,
            "message": "服务连通，实际调用成功"
            + ("（1024维）" if isinstance(connection, EmbeddingConnection) else "")
            + "；配置尚未保存。"
            if valid
            else "服务已响应，但返回格式或向量维数不符合要求；请检查协议和模型。",
        }
    except httpx.TimeoutException:
        return {
            "connected": connected,
            "callSucceeded": False,
            "message": "调用超时；请检查网络或服务响应时间。",
        }
    except httpx.HTTPError:
        return {
            "connected": connected,
            "callSucceeded": False,
            "message": "网络请求失败；请检查服务地址、网络连接和 TLS 证书。",
        }
    except (ValueError, KeyError, TypeError, IndexError, OverflowError, AnswerProtocolError):
        return {
            "connected": connected,
            "callSucceeded": False,
            "message": "服务已响应，但返回格式不符合所选协议；请检查协议和模型。",
        }
    finally:
        if owned:
            client.close()


def probe_model_settings(directory, payload):
    if not isinstance(payload, dict) or set(payload) != {"configuration", "kind", "modelId"}:
        raise ModelSettingsError("测试请求格式无效。")
    models = prepare_model_update(directory, payload["configuration"])
    if payload["kind"] == "embedding":
        connection = models.embedding
    elif payload["kind"] == "answer":
        connection = next(
            (item for item in models.answer_models if item.id == payload["modelId"]), None
        )
    else:
        raise ModelSettingsError("请选择要测试的模型用途。")
    if connection is None:
        raise ModelSettingsError("请先填写并启用要测试的模型。")
    return probe_connection(connection)
