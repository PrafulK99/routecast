"""Responses are gzip-compressed for clients that accept it."""

import gzip
import json

from .helpers import REQUEST_ID, analyze_payload

URL = "/api/analyze"
GZIP = {"HTTP_ACCEPT_ENCODING": "gzip"}


def test_a_large_response_is_compressed_for_a_client_that_accepts_gzip(client, providers):
    providers()
    plain = client.post(URL, analyze_payload(), format="json")

    compressed = client.post(URL, analyze_payload(), format="json", **GZIP)

    assert compressed["Content-Encoding"] == "gzip"
    assert "Accept-Encoding" in compressed["Vary"]
    assert len(compressed.content) < len(plain.content) / 3
    assert json.loads(gzip.decompress(compressed.content)) == plain.json()


def test_no_accept_encoding_means_an_unchanged_response(client, providers):
    providers()

    response = client.post(URL, analyze_payload(), format="json")

    assert "Content-Encoding" not in response
    assert response.json()["routes"]


def test_a_tiny_response_is_not_compressed(client):
    response = client.get("/api/health", **GZIP)

    assert response.status_code == 200
    assert "Content-Encoding" not in response


def test_compressed_and_error_responses_still_carry_the_request_id(client, providers):
    providers()

    ok = client.post(URL, analyze_payload(), format="json", **GZIP)
    bad = client.post(URL, {}, format="json", **GZIP)

    assert ok["X-Request-ID"] == REQUEST_ID
    assert bad.status_code == 400 and bad["X-Request-ID"] == REQUEST_ID
