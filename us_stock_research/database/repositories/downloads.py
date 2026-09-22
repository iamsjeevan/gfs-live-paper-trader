"""Repository for tracking download status and enabling resumable pipelines."""

from typing import Any, Dict, List, Optional, Set
import sqlite3


class DownloadStatusRepository:
    """Manages tracking of download jobs so interruptions can be resumed seamlessly."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def record_start(self, task_type: str, entity_id: str, source_url: Optional[str] = None) -> None:
        """Mark an entity download task as IN_PROGRESS."""
        sql = """
        INSERT INTO download_status (
            task_type, entity_id, status, started_at, attempts, source_url
        ) VALUES (?, ?, 'IN_PROGRESS', datetime('now'), 1, ?)
        ON CONFLICT(task_type, entity_id) DO UPDATE SET
            status = 'IN_PROGRESS',
            started_at = datetime('now'),
            attempts = download_status.attempts + 1,
            source_url = COALESCE(excluded.source_url, download_status.source_url);
        """
        self.conn.execute(sql, (task_type, str(entity_id), source_url))

    def record_success(
        self,
        task_type: str,
        entity_id: str,
        http_status: int = 200,
        file_path: Optional[str] = None,
    ) -> None:
        """Mark an entity download task as COMPLETED."""
        sql = """
        INSERT INTO download_status (
            task_type, entity_id, status, completed_at, http_status, file_path
        ) VALUES (?, ?, 'COMPLETED', datetime('now'), ?, ?)
        ON CONFLICT(task_type, entity_id) DO UPDATE SET
            status = 'COMPLETED',
            completed_at = datetime('now'),
            http_status = excluded.http_status,
            file_path = COALESCE(excluded.file_path, download_status.file_path),
            error_message = NULL;
        """
        self.conn.execute(sql, (task_type, str(entity_id), http_status, file_path))

    def record_failure(
        self,
        task_type: str,
        entity_id: str,
        error_message: str,
        http_status: Optional[int] = None,
    ) -> None:
        """Mark an entity download task as FAILED."""
        status = "NOT_FOUND" if http_status == 404 else "FAILED"
        sql = """
        INSERT INTO download_status (
            task_type, entity_id, status, completed_at, http_status, error_message
        ) VALUES (?, ?, ?, datetime('now'), ?, ?)
        ON CONFLICT(task_type, entity_id) DO UPDATE SET
            status = excluded.status,
            completed_at = datetime('now'),
            http_status = excluded.http_status,
            error_message = excluded.error_message;
        """
        self.conn.execute(sql, (task_type, str(entity_id), status, http_status, error_message))

    def is_completed(self, task_type: str, entity_id: str) -> bool:
        """Check if an entity has already been successfully downloaded."""
        sql = """
        SELECT 1 FROM download_status
        WHERE task_type = ? AND entity_id = ? AND status = 'COMPLETED'
        LIMIT 1;
        """
        cursor = self.conn.execute(sql, (task_type, str(entity_id)))
        return cursor.fetchone() is not None

    def get_completed_entity_ids(self, task_type: str) -> Set[str]:
        """Return the set of entity_ids that have completed successfully."""
        sql = "SELECT entity_id FROM download_status WHERE task_type = ? AND status = 'COMPLETED'"
        cursor = self.conn.execute(sql, (task_type,))
        return {str(row[0]) for row in cursor.fetchall()}

    def get_status(self, task_type: str, entity_id: str) -> Optional[Dict[str, Any]]:
        """Get full download status record for an entity."""
        sql = "SELECT * FROM download_status WHERE task_type = ? AND entity_id = ?"
        cursor = self.conn.execute(sql, (task_type, str(entity_id)))
        row = cursor.fetchone()
        return dict(row) if row else None
