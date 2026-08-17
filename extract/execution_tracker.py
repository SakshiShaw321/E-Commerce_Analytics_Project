"""Track and store execution history of scraper runs."""

import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
from config import DB_DIR


class ExecutionTracker:
    """Track execution history of scrapers in SQLite."""

    def __init__(self, db_path: str | Path | None = None):
        """Initialize the execution tracker."""
        self.db_path = db_path or DB_DIR / "execution_history.db"
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the database schema."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scraper_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TIMESTAMP NOT NULL,
                    ended_at TIMESTAMP,
                    duration_seconds REAL,
                    products_scraped INTEGER,
                    error_message TEXT,
                    output_file TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS scraper_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scraper_name TEXT UNIQUE NOT NULL,
                    total_runs INTEGER DEFAULT 0,
                    successful_runs INTEGER DEFAULT 0,
                    failed_runs INTEGER DEFAULT 0,
                    last_run_at TIMESTAMP,
                    last_success_at TIMESTAMP,
                    last_failure_at TIMESTAMP,
                    total_products_scraped INTEGER DEFAULT 0,
                    avg_duration_seconds REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()

    def record_start(self, scraper_name: str) -> int:
        """Record the start of a scraper execution."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO executions (scraper_name, status, started_at)
                VALUES (?, ?, ?)
                """,
                (scraper_name, "RUNNING", datetime.now().isoformat()),
            )
            conn.commit()
            return cursor.lastrowid

    def record_success(
        self,
        execution_id: int,
        products_scraped: int,
        output_file: str | None = None,
    ) -> None:
        """Record successful completion of a scraper execution."""
        duration = self._calculate_duration(execution_id)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE executions
                SET status = ?, ended_at = ?, duration_seconds = ?,
                    products_scraped = ?, output_file = ?
                WHERE id = ?
                """,
                (
                    "SUCCESS",
                    datetime.now().isoformat(),
                    duration,
                    products_scraped,
                    output_file,
                    execution_id,
                ),
            )
            conn.commit()
            self._update_stats(execution_id, "SUCCESS")

    def record_failure(self, execution_id: int, error_message: str) -> None:
        """Record failed completion of a scraper execution."""
        duration = self._calculate_duration(execution_id)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE executions
                SET status = ?, ended_at = ?, duration_seconds = ?,
                    error_message = ?
                WHERE id = ?
                """,
                (
                    "FAILED",
                    datetime.now().isoformat(),
                    duration,
                    error_message[:500],
                    execution_id,
                ),
            )
            conn.commit()
            self._update_stats(execution_id, "FAILED")

    def _calculate_duration(self, execution_id: int) -> float:
        """Calculate duration of execution in seconds."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT started_at FROM executions WHERE id = ?",
                (execution_id,),
            )
            row = cursor.fetchone()
            if row:
                started = datetime.fromisoformat(row[0])
                return (datetime.now() - started).total_seconds()
            return 0

    def _update_stats(self, execution_id: int, status: str) -> None:
        """Update scraper statistics."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT scraper_name, products_scraped FROM executions WHERE id = ?",
                (execution_id,),
            )
            row = cursor.fetchone()
            if not row:
                return

            scraper_name, products_scraped = row
            cursor.execute(
                "SELECT * FROM scraper_stats WHERE scraper_name = ?",
                (scraper_name,),
            )
            stats_row = cursor.fetchone()

            if stats_row:
                cursor.execute(
                    """
                    UPDATE scraper_stats
                    SET total_runs = total_runs + 1,
                        successful_runs = successful_runs + ?,
                        failed_runs = failed_runs + ?,
                        last_run_at = ?,
                        last_success_at = CASE WHEN ? = 'SUCCESS' THEN ? ELSE last_success_at END,
                        last_failure_at = CASE WHEN ? = 'FAILED' THEN ? ELSE last_failure_at END,
                        total_products_scraped = total_products_scraped + ?,
                        updated_at = ?
                    WHERE scraper_name = ?
                    """,
                    (
                        1 if status == "SUCCESS" else 0,
                        1 if status == "FAILED" else 0,
                        datetime.now().isoformat(),
                        status,
                        datetime.now().isoformat(),
                        status,
                        datetime.now().isoformat(),
                        products_scraped or 0,
                        datetime.now().isoformat(),
                        scraper_name,
                    ),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO scraper_stats
                    (scraper_name, total_runs, successful_runs, failed_runs,
                     last_run_at, last_success_at, last_failure_at, total_products_scraped)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        scraper_name,
                        1,
                        1 if status == "SUCCESS" else 0,
                        1 if status == "FAILED" else 0,
                        datetime.now().isoformat(),
                        datetime.now().isoformat() if status == "SUCCESS" else None,
                        datetime.now().isoformat() if status == "FAILED" else None,
                        products_scraped or 0,
                    ),
                )
            conn.commit()

    def get_recent_runs(self, scraper_name: str, limit: int = 10) -> list[dict]:
        """Get recent execution records for a scraper."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, scraper_name, status, started_at, ended_at,
                       duration_seconds, products_scraped, error_message, output_file
                FROM executions
                WHERE scraper_name = ?
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (scraper_name, limit),
            )
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_stats(self, scraper_name: str) -> Optional[dict]:
        """Get statistics for a scraper."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT scraper_name, total_runs, successful_runs, failed_runs,
                       last_run_at, last_success_at, last_failure_at,
                       total_products_scraped, avg_duration_seconds
                FROM scraper_stats
                WHERE scraper_name = ?
                """,
                (scraper_name,),
            )
            row = cursor.fetchone()
            if row:
                columns = [desc[0] for desc in cursor.description]
                return dict(zip(columns, row))
            return None

    def get_all_stats(self) -> list[dict]:
        """Get statistics for all scrapers."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT scraper_name, total_runs, successful_runs, failed_runs,
                       last_run_at, last_success_at, last_failure_at,
                       total_products_scraped, avg_duration_seconds
                FROM scraper_stats
                ORDER BY last_run_at DESC
                """
            )
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def cleanup_old_records(self, days: int = 30) -> int:
        """Delete execution records older than specified days."""
        cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM executions WHERE created_at < ?",
                (cutoff_date,),
            )
            conn.commit()
            return cursor.rowcount
