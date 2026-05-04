"""
E2E test fixtures.

Tests run against a live deployed URL provided via the PREVIEW_URL env var
(set by .github/workflows/preview.yml). For local runs, set it to your local
backend URL or your prod URL.
"""

import os

import pytest
import requests


@pytest.fixture(scope="session")
def base_url() -> str:
    url = os.environ.get("PREVIEW_URL")
    if not url:
        pytest.skip("PREVIEW_URL not set; skipping E2E tests")
    return url.rstrip("/")


@pytest.fixture(scope="session")
def http_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"content-type": "application/json"})
    return s
