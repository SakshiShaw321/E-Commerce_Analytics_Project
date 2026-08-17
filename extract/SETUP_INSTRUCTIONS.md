# Setup Instructions - Automated Scraper Scheduler

## What Was Created

Your e-commerce scrapers have been transformed into a professional, automated data pipeline that runs every 24 hours with zero manual intervention.

### New Files Created

#### Core Scheduler System
- **`config.py`** - Configuration for all scrapers, schedules, logging, and retry settings
- **`logger_setup.py`** - Professional logging with file rotation and console output
- **`execution_tracker.py`** - SQLite database to track all scraper runs and statistics
- **`scheduler.py`** - Main orchestrator that manages the scheduler and scraper execution
- **`cli.py`** - Command-line interface to start/manage/monitor scrapers

#### Documentation
- **`SCHEDULER_README.md`** - Complete user guide with examples and troubleshooting
- **`scheduler_requirements.txt`** - Python dependencies to install

### Directory Structure After Setup

```
E-Commerce_Analytics_Project/
├── ecommerce_analytics_project/
│   └── data/
│       ├── config.py                    ← NEW: Configuration
│       ├── logger_setup.py              ← NEW: Logging setup
│       ├── execution_tracker.py         ← NEW: Database tracking
│       ├── scheduler.py                 ← NEW: Main scheduler
│       ├── cli.py                       ← NEW: CLI tool
│       ├── myntra_scraper.py            ← Existing
│       ├── ajio_scraper.py              ← Existing
│       ├── snapdeal_scraper.py          ← Existing
│       ├── flipkart_scraper.py          ← Existing
│       ├── amazon_scraper.py            ← Existing
│       ├── raw_data/                    ← NEW: CSV output folder
│       ├── logs/                        ← NEW: Log files
│       │   ├── scheduler.log
│       │   ├── scraper.log
│       │   └── errors.log
│       └── metadata/
│           └── execution_history.db     ← NEW: Execution database
└── SCHEDULER_README.md                  ← NEW: Complete guide
```

## Step 1: Install Dependencies

```bash
cd D:\E-Commerce_Analytics_Project
pip install -r scheduler_requirements.txt
```

This installs:
- **apscheduler** - Advanced job scheduling library
- **pytz** - Timezone support
- Plus all dependencies your scrapers already use

## Step 2: Download Playwright Browsers (One-Time)

```bash
python -m playwright install
```

This is needed for Ajio, Snapdeal, Flipkart, and Amazon scrapers that use Playwright.

## Step 3: Start the Scheduler

```bash
cd ecommerce_analytics_project\data
python cli.py start
```

### Expected Output

```
================================================================================
STARTING AUTOMATED SCRAPER SCHEDULER
================================================================================

Schedule:
  • myntra        → 00:00 daily
  • ajio          → 02:00 daily
  • snapdeal      → 04:00 daily
  • flipkart      → 06:00 daily
  • amazon        → 08:00 daily

To stop the scheduler, press Ctrl+C

================================================================================
SCRAPER SCHEDULER STARTED
================================================================================
  ✓ Scraper: myntra → cron[hour='0', minute='0', ...]
  ✓ Scraper: ajio → cron[hour='2', minute='0', ...]
  ✓ Scraper: snapdeal → cron[hour='4', minute='0', ...]
  ✓ Scraper: flipkart → cron[hour='6', minute='0', ...]
  ✓ Scraper: amazon → cron[hour='8', minute='0', ...]
================================================================================
Scheduler is now running. Press Ctrl+C to stop.
```

**Leave this running!** The scheduler will continuously monitor and run scrapers at their scheduled times.

## Step 4: Monitoring & Management

While the scheduler is running in the background, open a new terminal to use management commands:

### View Current Status
```bash
python cli.py status
```

### Run a Scraper Immediately
```bash
python cli.py run myntra
python cli.py run ajio
```

### View Execution Statistics
```bash
python cli.py stats
```

### View Recent Runs for a Scraper
```bash
python cli.py history myntra
python cli.py history myntra 20  # Last 20 runs
```

### Clean Old Records (older than 30 days)
```bash
python cli.py cleanup 30
```

## What Happens Automatically

### Every 24 Hours, The Scheduler:

1. **Runs each scraper at its scheduled time** (00:00, 02:00, 04:00, 06:00, 08:00)
2. **Records execution details** in the database
3. **Logs all activities** to separate log files
4. **Saves data** to CSV files in `raw_data/` folder
5. **Tracks statistics** (success rate, product count, runtime)
6. **Retries automatically** if a scraper fails
7. **Sends errors to error log** for analysis

### Example Daily Execution Timeline

```
00:00 → Myntra starts scraping
00:15 → Myntra completes (500 products saved)
02:00 → Ajio starts scraping
02:45 → Ajio completes (450 products saved)
04:00 → Snapdeal starts scraping
04:50 → Snapdeal completes (400 products saved)
06:00 → Flipkart starts scraping
07:15 → Flipkart completes (600 products saved)
08:00 → Amazon starts scraping
09:10 → Amazon completes (550 products saved)
```

## Customizing Schedules

To change when scrapers run, edit `config.py`:

```python
SCRAPER_CONFIG = {
    "myntra": {
        "schedule_hour": 0,      # Change this (0-23)
        "schedule_minute": 0,    # Change this (0-59)
        # ... rest of config
    },
    "ajio": {
        "schedule_hour": 2,
        "schedule_minute": 0,
    },
    # ... more scrapers
}
```

Then restart the scheduler (`Ctrl+C` then `python cli.py start`).

## Understanding Log Files

### scheduler.log
Shows when jobs run and their basic status:
```
2026-08-17 00:00:00 - scheduler - INFO - Starting scraper: myntra
2026-08-17 00:15:32 - scheduler - INFO - [myntra] ✓ SUCCESS: Scraped 500 products in 385.2s
```

### scraper.log
Detailed logs from each scraper's execution:
```
2026-08-17 00:00:05 - scraper - INFO - [myntra] Running with keyword='women shirts'
2026-08-17 00:01:20 - scraper - INFO - [myntra] Page 1: 50 women's shirts (50 total so far)
2026-08-17 00:15:20 - scraper - INFO - [myntra] Scraped 500 products -> saved to raw_data/myntra_women_shirts_raw.csv
```

### errors.log
Any exceptions or failures:
```
2026-08-14 00:16:00 - errors - ERROR - [myntra] ✗ FAILED after ConnectionError
Traceback (most recent call last):
  File "scheduler.py", line 52, in run_scraper
    data = scraper_func(...)
ConnectionError: Max retries exceeded
```

## Database Schema

The `execution_history.db` SQLite database tracks every run:

### executions table
- When each scraper ran
- How long it took
- If it succeeded or failed
- How many products were scraped
- Any error messages
- Output file location

### scraper_stats table
- Success/failure rates per scraper
- Total products scraped
- Average execution time
- Last run timestamp

Query examples:
```python
from execution_tracker import ExecutionTracker

tracker = ExecutionTracker()

# Get recent runs
runs = tracker.get_recent_runs("myntra", limit=10)

# Get statistics
stats = tracker.get_stats("myntra")
print(f"Success rate: {stats['successful_runs']}/{stats['total_runs']}")

# Get all scrapers' stats
all_stats = tracker.get_all_stats()
```

## Keeping the Scheduler Running

### Option 1: Keep Terminal Open (Development)
Simply keep the terminal running with `python cli.py start`.

### Option 2: Windows Service (Production)
Use NSSM to run as a Windows service:

```bash
# Download from https://nssm.cc/
nssm install EcommerceScraper python.exe cli.py start
nssm start EcommerceScraper
```

See `SCHEDULER_README.md` for details on setting up as a Windows service.

### Option 3: Task Scheduler (Backup Alternative)
Set up Windows Task Scheduler to run `cli.py start` at system startup.

## Troubleshooting

### Issue: Scheduler starts but doesn't run scrapers

1. **Verify scrapers are enabled** in `config.py`:
   ```python
   "myntra": {
       "enabled": True,  # Should be True
   }
   ```

2. **Check scheduler status**:
   ```bash
   python cli.py status
   ```

3. **View error logs**:
   ```bash
   type logs\errors.log
   ```

### Issue: A scraper keeps failing

1. **View recent runs**:
   ```bash
   python cli.py history myntra 5
   ```

2. **Check error logs**:
   ```bash
   type logs\errors.log | findstr myntra
   ```

3. **Try running manually**:
   ```bash
   python cli.py run myntra
   ```

4. **Check network connection** - The scraper might be blocked

### Issue: High disk usage

Old CSV files accumulate over time. Clean up:

```bash
# Delete CSV files older than 60 days
cd ecommerce_analytics_project\data\raw_data
# Manually delete or use a file cleanup utility

# Clean database records older than 30 days
python cli.py cleanup 30
```

## Next Steps

1. ✅ Install dependencies: `pip install -r scheduler_requirements.txt`
2. ✅ Install Playwright: `python -m playwright install`
3. ✅ Start scheduler: `cd ecommerce_analytics_project\data && python cli.py start`
4. ✅ Monitor with: `python cli.py status` / `python cli.py stats`
5. ✅ View logs: `logs/scheduler.log`, `logs/scraper.log`, `logs/errors.log`

## Success Indicators

After 24 hours, you should see:
- ✓ Five new CSV files in `raw_data/` (one per scraper)
- ✓ Detailed logs in `logs/` folder
- ✓ Execution history in `metadata/execution_history.db`
- ✓ Statistics showing successful runs and product counts

## Configuration Reference

Key settings in `config.py`:

```python
# Individual scraper schedules (in 24-hour format)
SCRAPER_CONFIG = {
    "myntra": {"schedule_hour": 0, "schedule_minute": 0, ...},
    "ajio": {"schedule_hour": 2, "schedule_minute": 0, ...},
    # ...
}

# Retry configuration for failed scrapers
RETRY_CONFIG = {
    "max_retries": 3,           # Try up to 3 times
    "retry_delay": 300,         # Wait 5 minutes before retry
    "backoff_factor": 2,        # Double wait time each retry
}

# Logging level
LOGGING_CONFIG = {
    "level": "INFO",  # Can be DEBUG, INFO, WARNING, ERROR
}
```

## Support

For detailed documentation, see **SCHEDULER_README.md** which includes:
- Complete CLI command reference
- Database schema details
- Running as a Windows service
- API usage examples
- Performance tips
- Troubleshooting guide

---

**Your scrapers are now automated! They'll run every 24 hours without any manual intervention. 🚀**
