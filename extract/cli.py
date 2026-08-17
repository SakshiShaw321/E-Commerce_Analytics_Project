"""CLI tool for managing the scraper scheduler."""

import argparse
import sys
from scheduler import ScraperScheduler
from execution_tracker import ExecutionTracker
from logger_setup import scheduler_logger


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Automated E-commerce Scraper Scheduler",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cli.py start              Start the scheduler (daily jobs)
  python cli.py run myntra         Run myntra scraper immediately
  python cli.py status             Show scheduler status
  python cli.py stats              Show execution statistics
  python cli.py history myntra 10  Show last 10 runs for myntra
  python cli.py cleanup 30         Clean records older than 30 days
        """,
    )

    parser.add_argument(
        "command",
        choices=["start", "run", "status", "stats", "history", "cleanup", "help"],
        help="Command to execute",
    )
    parser.add_argument(
        "arguments",
        nargs="*",
        help="Arguments for the command",
    )

    args = parser.parse_args()

    scheduler = ScraperScheduler()
    tracker = ExecutionTracker()

    if args.command == "start":
        print("\n" + "=" * 80)
        print("STARTING AUTOMATED SCRAPER SCHEDULER")
        print("=" * 80)
        print("\nSchedule:")
        from config import SCRAPER_CONFIG
        for name, config in SCRAPER_CONFIG.items():
            if config.get("enabled"):
                hour = config.get("schedule_hour", 0)
                minute = config.get("schedule_minute", 0)
                print(f"  • {name:12} → {hour:02d}:{minute:02d} daily")
        print("\nTo stop the scheduler, press Ctrl+C\n")
        try:
            scheduler.start()
        except KeyboardInterrupt:
            print("\n\nScheduler stopped by user.")
            sys.exit(0)

    elif args.command == "run":
        if not args.arguments:
            print("Error: specify a scraper name (e.g., 'myntra')")
            sys.exit(1)
        scraper_name = args.arguments[0]
        success = scheduler.run_scraper_now(scraper_name)
        sys.exit(0 if success else 1)

    elif args.command == "status":
        status = scheduler.get_status()
        print("\n" + "=" * 80)
        print("SCHEDULER STATUS")
        print("=" * 80)
        print(f"Running: {status['running']}")
        print(f"Active jobs: {status['total_jobs']}\n")
        if status["jobs"]:
            for job in status["jobs"]:
                print(f"  • {job['name']}")
                print(f"    Next run: {job['next_run']}")
                print(f"    Trigger: {job['trigger']}\n")
        print("=" * 80 + "\n")

    elif args.command == "stats":
        scheduler.print_stats()

    elif args.command == "history":
        if not args.arguments:
            print("Error: specify a scraper name (e.g., 'myntra')")
            sys.exit(1)
        scraper_name = args.arguments[0]
        limit = int(args.arguments[1]) if len(args.arguments) > 1 else 10

        runs = tracker.get_recent_runs(scraper_name, limit)
        if not runs:
            print(f"No execution history found for '{scraper_name}'")
            sys.exit(0)

        print("\n" + "=" * 100)
        print(f"RECENT EXECUTION HISTORY: {scraper_name.upper()}")
        print("=" * 100)
        print(f"{'Status':<10} {'Started':<20} {'Duration':<12} {'Products':<10} {'Message':<48}")
        print("-" * 100)

        for run in runs:
            status = run["status"]
            started = run["started_at"][:19] if run["started_at"] else "N/A"
            duration = f"{run['duration_seconds']:.1f}s" if run["duration_seconds"] else "N/A"
            products = str(run["products_scraped"]) if run["products_scraped"] else "0"
            message = (
                run["error_message"][:47] + "..."
                if run["error_message"] and len(run["error_message"]) > 47
                else (run["error_message"] or "Success")
            )

            status_icon = "✓" if status == "SUCCESS" else "✗"
            print(f"{status_icon} {status:<8} {started:<20} {duration:<12} {products:<10} {message:<48}")

        print("=" * 100 + "\n")

    elif args.command == "cleanup":
        days = int(args.arguments[0]) if args.arguments else 30
        count = tracker.cleanup_old_records(days)
        print(f"Deleted {count} execution records older than {days} days.")

    elif args.command == "help":
        parser.print_help()


if __name__ == "__main__":
    main()
