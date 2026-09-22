"""SEC EDGAR API HTTP Client.

Implements fair-access compliance:
- Strict thread-safe rate limiting (default <= 8 req/sec, SEC limit is 10)
- Configured User-Agent header in required format
- Automatic retries with exponential backoff on 429 (Rate Limit) and 5xx
- Local raw caching with atomic writes
"""

import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Union

import requests

from config.settings import (
    SEC_BACKOFF_FACTOR,
    SEC_MAX_RETRIES,
    SEC_RATE_LIMIT_PER_SEC,
    SEC_TIMEOUT,
    SEC_USER_AGENT,
    setup_logger,
)

logger = setup_logger("sec_client", "sec_download.log")


class RateLimiter:
    """Thread-safe leaky-bucket rate limiter to enforce SEC fair access policy."""

    def __init__(self, requests_per_second: float = 8.0):
        self.interval = 1.0 / max(0.1, requests_per_second)
        self.lock = threading.Lock()
        self.last_request_time = 0.0

    def wait(self) -> None:
        """Block until next request window is available."""
        with self.lock:
            now = time.time()
            elapsed = now - self.last_request_time
            if elapsed < self.interval:
                time.sleep(self.interval - elapsed)
            self.last_request_time = time.time()


class SECClient:
    """Client for interacting with SEC EDGAR REST APIs."""

    def __init__(
        self,
        user_agent: Optional[str] = None,
        rate_limit_per_sec: float = SEC_RATE_LIMIT_PER_SEC,
        timeout: float = SEC_TIMEOUT,
        max_retries: int = SEC_MAX_RETRIES,
        backoff_factor: float = SEC_BACKOFF_FACTOR,
    ):
        self.user_agent = user_agent or SEC_USER_AGENT
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.rate_limiter = RateLimiter(rate_limit_per_sec)

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Accept": "application/json, text/plain, */*",
        })

    def get(
        self,
        url: str,
        cache_path: Optional[Union[str, Path]] = None,
        refresh: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Perform a GET request with caching, rate-limiting, and retries.

        Args:
            url: Full SEC URL.
            cache_path: Optional path to raw JSON file cache.
            refresh: If True, bypass cache and re-download.

        Returns:
            Parsed JSON dict, or None if 404 (Not Found).
        """
        # 1. Check local cache first
        if cache_path is not None and not refresh:
            cpath = Path(cache_path)
            if cpath.exists() and cpath.stat().st_size > 0:
                try:
                    with open(cpath, "r", encoding="utf-8") as f:
                        return json.load(f)
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning(f"Corrupt cache file at {cpath}: {exc}. Re-fetching.")

        # 2. Rate limiting & HTTP request loop
        for attempt in range(1, self.max_retries + 1):
            self.rate_limiter.wait()
            try:
                response = self.session.get(url, timeout=self.timeout)

                # HTTP 200 OK
                if response.status_code == 200:
                    try:
                        data = response.json()
                    except json.JSONDecodeError as exc:
                        logger.error(f"JSON decode failed for {url}: {exc}")
                        raise

                    # Save to cache atomically if cache_path specified
                    if cache_path is not None:
                        self._save_cache_atomic(Path(cache_path), response.text)

                    return data

                # HTTP 404 Not Found
                if response.status_code == 404:
                    logger.info(f"Resource not found (HTTP 404): {url}")
                    return None

                # HTTP 429 Too Many Requests
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    sleep_sec = float(retry_after) if retry_after else (self.backoff_factor ** attempt) * 2.0
                    logger.warning(
                        f"SEC Rate limit exceeded (429) on {url}. Backing off {sleep_sec:.1f}s (attempt {attempt}/{self.max_retries})"
                    )
                    time.sleep(sleep_sec)
                    continue

                # HTTP 5xx Server Error
                if response.status_code >= 500:
                    sleep_sec = (self.backoff_factor ** attempt)
                    logger.warning(f"SEC Server error ({response.status_code}) on {url}. Retrying in {sleep_sec:.1f}s")
                    time.sleep(sleep_sec)
                    continue

                # Other HTTP errors
                response.raise_for_status()

            except (requests.exceptions.RequestException, requests.exceptions.Timeout) as exc:
                sleep_sec = (self.backoff_factor ** attempt)
                logger.warning(
                    f"Network error requesting {url}: {exc}. Retrying in {sleep_sec:.1f}s (attempt {attempt}/{self.max_retries})"
                )
                time.sleep(sleep_sec)

        raise RuntimeError(f"Failed to fetch {url} after {self.max_retries} attempts.")

    @staticmethod
    def _save_cache_atomic(path: Path, content: str) -> None:
        """Write content to a temporary file then atomically replace target path."""
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_file = path.with_suffix(".tmp")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write(content)
            temp_file.replace(path)
        except Exception:
            if temp_file.exists():
                temp_file.unlink()
            raise
