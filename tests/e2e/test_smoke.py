"""
End-to-end smoke tests against a deployed RAG system.

These run against the URL in $PREVIEW_URL and exercise the real DB + LLM stack.
Designed to:
- Tolerate cold starts (Fly auto-stop + Neon autosuspend)
- Validate functional contract, not exact output
- Catch regressions in retrieval quality (top hit must be from expected ADR)
"""

import json
import time

import pytest
import requests

# Generous total budget for a cold start: Fly (~10s) + Neon (~2s) + first inference (~3s)
COLD_START_BUDGET_S = 90
WARM_QUERY_BUDGET_MS = 5000


def wait_for_health(http_session, base_url: str, budget_s: int = COLD_START_BUDGET_S) -> dict:
    """Poll /health until 200 or budget expires. Returns parsed JSON on success."""
    deadline = time.monotonic() + budget_s
    last_err = None
    while time.monotonic() < deadline:
        try:
            r = http_session.get(f"{base_url}/health", timeout=30)
            if r.status_code == 200:
                return r.json()
            last_err = f"HTTP {r.status_code}: {r.text[:200]}"
        except requests.exceptions.RequestException as e:
            last_err = str(e)
        time.sleep(5)
    pytest.fail(f"Health check did not return 200 within {budget_s}s. Last: {last_err}")


@pytest.fixture(scope="session", autouse=True)
def warm_up(http_session, base_url):
    """Wake the deployment before any other test runs."""
    health = wait_for_health(http_session, base_url)
    assert health["status"] == "healthy", f"Service unhealthy: {health}"
    return health


def test_health_returns_healthy(http_session, base_url, warm_up):
    """Health endpoint reports both database and LLM as healthy."""
    r = http_session.get(f"{base_url}/health", timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "healthy"
    assert body["database"] == "healthy"
    assert body["llm_api"] == "healthy"


def test_query_returns_answer_and_sources(http_session, base_url, warm_up):
    """Real query produces an answer with at least one source chunk."""
    r = http_session.post(
        f"{base_url}/query",
        data=json.dumps({"query": "how do we handle node health monitoring?"}),
        timeout=60,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answer"], "Empty answer"
    assert len(body["sources"]) > 0, "No sources retrieved"
    assert body["metadata"]["llm_latency_ms"] > 0
    assert body["metadata"]["embedding_latency_ms"] > 0


def test_query_retrieves_correct_adr(http_session, base_url, warm_up):
    """Retrieval relevance regression test: query about secrets must surface ADR-008."""
    r = http_session.post(
        f"{base_url}/query",
        data=json.dumps({"query": "what is our secret rotation policy?"}),
        timeout=60,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    top_titles = [s.get("title", "") for s in body["sources"][:3]]
    assert any(
        "secret_rotation" in t.lower() for t in top_titles
    ), f"Expected adr_008_secret_rotation in top 3 sources, got: {top_titles}"


def test_query_warm_latency(http_session, base_url, warm_up):
    """After warm-up, query latency stays under budget."""
    r = http_session.post(
        f"{base_url}/query",
        data=json.dumps({"query": "kubernetes cost optimization"}),
        timeout=30,
    )
    assert r.status_code == 200
    latency = r.json()["metadata"]["latency_ms"]
    assert latency < WARM_QUERY_BUDGET_MS, f"Warm query took {latency}ms, exceeds {WARM_QUERY_BUDGET_MS}ms budget"


def test_unknown_query_does_not_500(http_session, base_url, warm_up):
    """A query unrelated to the KB returns gracefully, not 500."""
    r = http_session.post(
        f"{base_url}/query",
        data=json.dumps({"query": "what is the airspeed velocity of an unladen swallow?"}),
        timeout=60,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Either retrieves something with low similarity or returns no sources;
    # either way must not error.
    assert "answer" in body
