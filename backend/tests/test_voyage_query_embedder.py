"""Provider adapter sends versioned query settings and validates results."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.integrations.voyage import EmbeddingProviderError, VoyageQueryEmbedder

VECTOR = [0.0] * 1024


def _payload(*entries):
    return {"model": "voyage-4", "data": list(entries)}


def _entry(index=0, embedding=None):
    return {"index": index, "embedding": VECTOR if embedding is None else embedding}


def _with_component(value):
    return [value, *([0.0] * 1023)]


def _embed_payload(payload, texts=None):
    async def run():
        transport = httpx.MockTransport(lambda _: httpx.Response(
            200, content=json.dumps(payload),
        ))
        async with httpx.AsyncClient(transport=transport) as client:
            return await VoyageQueryEmbedder("test-key", client).embed_queries(
                texts or ["TITLE: Title\nSUMMARY: Summary"]
            )

    return asyncio.run(run())


def test_voyage_query_embedding_uses_reviewed_identity_and_dimension():
    captured = {}
    vector = [1.0] + [0.0] * 1023

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["authorization"]
        captured["payload"] = __import__("json").loads(request.content)
        return httpx.Response(200, json={"model": "voyage-4", "data": [
            {"index": 0, "embedding": vector},
        ]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await VoyageQueryEmbedder("test-key", client).embed_queries(
                ["TITLE: Title\nSUMMARY: Summary"]
            )

    assert asyncio.run(run()) == [vector]
    assert captured["url"] == "https://api.voyageai.com/v1/embeddings"
    assert captured["authorization"] == "Bearer test-key"
    assert captured["payload"] == {
        "input": ["TITLE: Title\nSUMMARY: Summary"], "model": "voyage-4",
        "input_type": "query", "output_dimension": 1024,
        "output_dtype": "float", "truncation": False,
    }


@pytest.mark.parametrize("payload", [
    pytest.param([], id="top-level-list"),
    pytest.param(None, id="top-level-null"),
    pytest.param("response", id="top-level-string"),
    pytest.param(123, id="top-level-number"),
    pytest.param(True, id="top-level-bool"),
    pytest.param({"data": [_entry()]}, id="missing-model"),
    pytest.param({"model": None, "data": [_entry()]}, id="null-model"),
    pytest.param({"model": 4, "data": [_entry()]}, id="nonstr-model"),
    pytest.param({"model": "other", "data": [_entry()]}, id="wrong-model"),
    pytest.param({"model": "voyage-4"}, id="missing-data"),
    pytest.param({"model": "voyage-4", "data": None}, id="null-data"),
    pytest.param({"model": "voyage-4", "data": {}}, id="object-data"),
    pytest.param({"model": "voyage-4", "data": "entry"}, id="string-data"),
    pytest.param({"model": "voyage-4", "data": 1}, id="scalar-data"),
    pytest.param(_payload(), id="wrong-count"),
    pytest.param(_payload(None), id="null-entry"),
    pytest.param(_payload([]), id="list-entry"),
    pytest.param(_payload("entry"), id="string-entry"),
    pytest.param(_payload(42), id="number-entry"),
    pytest.param(_payload({"embedding": VECTOR}), id="missing-index"),
    pytest.param(_payload(_entry(None)), id="null-index"),
    pytest.param(_payload(_entry(True)), id="bool-index"),
    pytest.param(_payload(_entry(0.0)), id="float-index"),
    pytest.param(_payload(_entry("0")), id="string-index"),
    pytest.param(_payload(_entry(-1)), id="negative-index"),
    pytest.param(_payload(_entry(1)), id="out-of-range-index"),
    pytest.param(_payload({"index": 0}), id="missing-embedding"),
    pytest.param(_payload({"index": 0, "embedding": None}), id="null-embedding"),
    pytest.param(_payload(_entry(embedding={})), id="object-embedding"),
    pytest.param(_payload(_entry(embedding="vector")), id="string-embedding"),
    pytest.param(_payload(_entry(embedding=42)), id="scalar-embedding"),
    pytest.param(_payload(_entry(embedding=[0.0])), id="wrong-dimension"),
    pytest.param(_payload(_entry(embedding=_with_component(float("nan")))), id="nan"),
    pytest.param(_payload(_entry(embedding=_with_component(float("inf")))), id="positive-infinity"),
    pytest.param(_payload(_entry(embedding=_with_component(float("-inf")))), id="negative-infinity"),
    pytest.param(_payload(_entry(embedding=_with_component(True))), id="bool-component"),
    pytest.param(_payload(_entry(embedding=_with_component("1"))), id="string-component"),
    pytest.param(_payload(_entry(embedding=_with_component(None))), id="null-component"),
    pytest.param(_payload(_entry(embedding=_with_component({}))), id="object-component"),
    pytest.param(_payload(_entry(embedding=_with_component(10**1000))), id="overflow-component"),
])
def test_malformed_payloads_raise_provider_error(payload):
    with pytest.raises(EmbeddingProviderError):
        _embed_payload(payload)


@pytest.mark.parametrize("indices", [(0, 0), (0, 2), (1, 1), (-1, 0)])
def test_invalid_two_item_indices_raise_provider_error(indices):
    with pytest.raises(EmbeddingProviderError):
        _embed_payload(
            _payload(*(_entry(index) for index in indices)),
            ["TITLE: One\nSUMMARY: One", "TITLE: Two\nSUMMARY: Two"],
        )


def test_out_of_order_indices_are_returned_in_input_order():
    result = _embed_payload(
        _payload(_entry(1, _with_component(2)), _entry(0, _with_component(1))),
        ["TITLE: One\nSUMMARY: One", "TITLE: Two\nSUMMARY: Two"],
    )
    assert result == [_with_component(1.0), _with_component(2.0)]


@pytest.mark.parametrize("response", [
    httpx.Response(500, text="private provider error"),
    httpx.Response(200, content=b"not JSON"),
])
def test_http_and_json_failures_raise_provider_error(response):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response)) as client:
            await VoyageQueryEmbedder("test-key", client).embed_queries(["TITLE: X\nSUMMARY: Y"])

    with pytest.raises(EmbeddingProviderError) as raised:
        asyncio.run(run())
    assert "private provider error" not in str(raised.value)


def test_oversized_json_integer_decode_failure_raises_provider_error():
    body = b'{"model":"voyage-4","data":' + b"9" * 5000 + b"}"

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _: httpx.Response(200, content=body)
        )) as client:
            await VoyageQueryEmbedder("test-key", client).embed_queries(["TITLE: X\nSUMMARY: Y"])

    with pytest.raises(EmbeddingProviderError):
        asyncio.run(run())


def test_each_batch_is_validated_and_malformed_later_batch_fails():
    calls = []

    def handler(request):
        batch = json.loads(request.content)["input"]
        calls.append(len(batch))
        if len(batch) == 1:
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=_payload(*(_entry(i) for i in range(64))))

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await VoyageQueryEmbedder("test-key", client).embed_queries(["query"] * 65)

    with pytest.raises(EmbeddingProviderError):
        asyncio.run(run())
    assert calls == [64, 1]
