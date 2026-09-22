"""Unit tests for the resumable downloader logic."""

import sqlite3
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from database.schema import SCHEMA_DDL
from database.repositories.downloads import DownloadStatusRepository
from data_sources.sec.downloader import download_all_sec_data


@pytest.fixture
def test_db_path(tmp_path):
    db_file = tmp_path / "test_research.db"
    conn = sqlite3.connect(db_file)
    conn.executescript(SCHEMA_DDL)
    conn.commit()
    conn.close()
    return db_file


def test_downloader_resume_skips_completed(test_db_path):
    """Test that download_all_sec_data skips CIKs already marked as COMPLETED in SQLite."""
    conn = sqlite3.connect(test_db_path)
    status_repo = DownloadStatusRepository(conn)
    # Pretend CIK 1001 and 1002 were already successfully downloaded
    status_repo.record_success("sec_companyfacts", "1001", http_status=200, file_path="cache/1001.json")
    status_repo.record_success("sec_companyfacts", "1002", http_status=200, file_path="cache/1002.json")
    conn.commit()
    conn.close()

    ciks = [1001, 1002, 1003]

    # Mock download_single_company so it doesn't hit real SEC
    with patch("data_sources.sec.downloader.download_single_company") as mock_dl:
        mock_dl.return_value = {"cik": 1003, "status": "COMPLETED", "http_status": 200}

        summary = download_all_sec_data(
            ciks=ciks,
            task_type="sec_companyfacts",
            workers=1,
            resume=True,
            db_path=test_db_path,
        )

        assert summary["SKIPPED"] == 2
        assert summary["COMPLETED"] == 1
        # Only 1003 should have been called!
        assert mock_dl.call_count == 1
        call_cik = mock_dl.call_args[0][0]
        assert call_cik == 1003
