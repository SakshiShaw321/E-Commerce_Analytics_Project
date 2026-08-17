"""Automated scheduler for running scrapers on a schedule."""

import sys
import time
import importlib
from datetime import datetime
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config import SCRAPER_CONFIG, SCHEDULER_CONFIG, RETRY_CONFIG
from logger_setup import scheduler_logger, scraper_logger, error_logger
from execution_tracker import ExecutionTracker


class ScraperScheduler:
    """Orchestrate automatic scraper execution."""

    def __init__(self):
        """Initialize the scheduler."""
        self.scheduler = BackgroundScheduler(**SCHEDULER_CONFIG)
        self.tracker = ExecutionTracker()
        self.scrapers_dir = Path(__file__).parent
        sys.path.insert(0, str(self.scrapers_dir))

    def run_scraper(self, scraper_name: str, config: dict) -> None:
        """Execute a single scraper with error handling and retry logic."""
        scraper_logger.info(f"Starting scraper: {scraper_name}")
        execution_id = self.tracker.record_start(scraper_name)

        try:
            module_name = config["module"]
            function_name = config["function"]
            output_file = config.get("output_file")
            keyword = config.get("keyword", "women shirts")
            max_products = config.get("max_products")
            max_pages = config.get("max_pages")
            search_only = config.get("search_only", True)

            scraper_module = importlib.import_module(module_name)
            scraper_func = getattr(scraper_module, function_name)

            scraper_logger.info(
                f"[{scraper_name}] Running with keyword='{keyword}', "
                f"max_products={max_products}, search_only={search_only}"
            )

            start_time = datetime.now()
            data = scraper_func(
                keyword=keyword,
                max_products=max_products,
                max_pages=max_pages,
                search_only=search_only,
            )
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()

            if data and output_file:
                module = importlib.import_module(module_name)
                save_func = getattr(module, "save_to_csv")
                saved_path = save_func(data, str(output_file))
                scraper_logger.info(
                    f"[{scraper_name}] ✓ SUCCESS: Scraped {len(data)} products "
                    f"in {duration:.1f}s → {saved_path}"
                )
                self.tracker.record_success(execution_id, len(data), saved_path)
            else:
                scraper_logger.warning(
                    f"[{scraper_name}] ⚠ No data scraped or output file not configured"
                )
                self.tracker.record_success(execution_id, 0, str(output_file))

        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {str(exc)}"
            error_logger.error(
                f"[{scraper_name}] ✗ FAILED after {type(exc).__name__}",
                exc_info=True,
            )
            scraper_logger.error(f"[{scraper_name}] {error_msg}")
            self.tracker.record_failure(execution_id, error_msg)

            if RETRY_CONFIG.get("max_retries", 0) > 0:
                self._schedule_retry(scraper_name, config, execution_id, 1)

    def _schedule_retry(
        self, scraper_name: str, config: dict, execution_id: int, attempt: int
    ) -> None:
        """Schedule a retry for a failed scraper."""
        max_retries = RETRY_CONFIG.get("max_retries", 3)
        if attempt <= max_retries:
            delay_seconds = (
                RETRY_CONFIG.get("retry_delay", 300)
                * (RETRY_CONFIG.get("backoff_factor", 2) ** (attempt - 1))
            )
            scraper_logger.info(
                f"[{scraper_name}] Retrying in {delay_seconds}s "
                f"(attempt {attempt}/{max_retries})"
            )
            self.scheduler.add_job(
                self.run_scraper,
                IntervalTrigger(seconds=int(delay_seconds)),
                args=(scraper_name, config),
                id=f"{scraper_name}_retry_{execution_id}_{attempt}",
                max_instances=1,
            )

    def schedule_scraper(self, scraper_name: str, config: dict) -> None:
        """Schedule a scraper to run on a regular interval."""
        if not config.get("enabled", True):
            scheduler_logger.info(f"Skipping disabled scraper: {scraper_name}")
            return

        hour = config.get("schedule_hour", 0)
        minute = config.get("schedule_minute", 0)

        trigger = CronTrigger(
            hour=hour,
            minute=minute,
            timezone=SCHEDULER_CONFIG["timezone"],
        )
        job_id = f"scraper_{scraper_name}"
        job = self.scheduler.add_job(
            self.run_scraper,
            trigger,
            args=(scraper_name, config),
            id=job_id,
            name=f"Scraper: {scraper_name}",
            max_instances=1,
        )
        scheduler_logger.info(
            f"Scheduled {scraper_name} to run daily at {hour:02d}:{minute:02d}"
        )
        return job

    def start(self) -> None:
        """Start the scheduler."""
        try:
            for scraper_name, config in SCRAPER_CONFIG.items():
                self.schedule_scraper(scraper_name, config)

            scheduler_logger.info("=" * 60)
            scheduler_logger.info("SCRAPER SCHEDULER STARTED")
            scheduler_logger.info("=" * 60)
            for job in self.scheduler.get_jobs():
                scheduler_logger.info(f"  ✓ {job.name} → {job.trigger}")
            scheduler_logger.info("=" * 60)

            self.scheduler.start()
            scheduler_logger.info("Scheduler is now running. Press Ctrl+C to stop.")

            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                scheduler_logger.info("Scheduler interrupted by user.")
        except Exception as exc:
            error_logger.error("Failed to start scheduler", exc_info=True)
            raise

    def stop(self) -> None:
        """Stop the scheduler gracefully."""
        if self.scheduler.running:
            scheduler_logger.info("Stopping scheduler...")
            self.scheduler.shutdown(wait=True)
            scheduler_logger.info("Scheduler stopped.")

    def get_status(self) -> dict:
        """Get current scheduler status."""
        jobs = [
            {
                "id": job.id,
                "name": job.name,
                "next_run": str(job.next_run_time),
                "trigger": str(job.trigger),
            }
            for job in self.scheduler.get_jobs()
        ]
        return {
            "running": self.scheduler.running,
            "jobs": jobs,
            "total_jobs": len(jobs),
        }

    def run_scraper_now(self, scraper_name: str) -> bool:
        """Manually trigger a scraper to run immediately."""
        if scraper_name not in SCRAPER_CONFIG:
            scheduler_logger.error(f"Unknown scraper: {scraper_name}")
            return False

        config = SCRAPER_CONFIG[scraper_name]
        scheduler_logger.info(f"Running {scraper_name} immediately...")
        self.run_scraper(scraper_name, config)
        return True

    def print_stats(self) -> None:
        """Print execution statistics for all scrapers."""
        print("\n" + "=" * 80)
        print("SCRAPER EXECUTION STATISTICS")
        print("=" * 80)

        stats = self.tracker.get_all_stats()
        if not stats:
            print("No execution statistics available yet.")
            return

        for stat in stats:
            success_rate = (
                (stat["successful_runs"] / stat["total_runs"] * 100)
                if stat["total_runs"] > 0
                else 0
            )
            print(f"\n{stat['scraper_name'].upper()}")
            print("-" * 40)
            print(f"  Total runs: {stat['total_runs']}")
            print(f"  Successful: {stat['successful_runs']} ({success_rate:.1f}%)")
            print(f"  Failed: {stat['failed_runs']}")
            print(f"  Total products: {stat['total_products_scraped']}")
            print(f"  Last run: {stat['last_run_at']}")

        print("\n" + "=" * 80 + "\n")


if __name__ == "__main__":
    import signal

    scheduler = ScraperScheduler()

    def signal_handler(signum, frame):
        scheduler.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    scheduler.start()
