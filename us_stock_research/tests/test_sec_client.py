"""Unit tests for the SEC HTTP Client, RateLimiter, and raw caching."""

import json
import time
from pathlib import Path
import pytest

from data_sources.sec.client import RateLimiter, SECClient


def test_rate_limiter_spacing():
    """Verify that the rate limiter enforces the minimum spacing between requests."""
    rate = 10.0  # 10 req/s -> interval = 0.1s
    limiter = RateLimiter(requests_per_second=rate)

    t0 = time.time()
    limiter.wait()
    limiter.wait()
    limiter.wait()
    elapsed = time.time() - t0

    # 3 requests need at least 2 intervals = ~0.20s
    assert elapsed >= 0.18, f"Expected elapsed >= 0.18s, got {elapsed:.3f}s"


def test_sec_client_headers():
    """Verify that User-Agent and headers comply with SEC format."""
    ua = "CustomResearchBot researcher@test.org"
    client = SECClient(user_agent=ua)
    assert client.session.headers["User-Agent"] == ua
    assert "gzip" in client.session.headers["Accept-Encoding"]


def test_sec_client_cache_read(tmp_path):
    """Verify that if a local raw JSON file exists, SECClient returns it without network request."""
    client = SECClient()
    cached_file = tmp_path / "CIK0000001234.json"
    sample_payload = {"cik": 1234, "name": "Cached Test Corp"}

    with open(cached_file, "w", encoding="utf-8") as f:
        json.dump(sample_payload, f)

    # Use a dummy non-routable URL to prove no network request occurs
    result = client.get("https://invalid.sec.gov/dummy", cache_path=cached_file, refresh=False)
    assert result == sample_payload
