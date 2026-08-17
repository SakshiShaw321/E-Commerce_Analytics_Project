# Automated E-Commerce Scraper Scheduler

Professional automated scraping system that runs your e-commerce scrapers every 24 hours like a data engineer does. The system is production-ready with logging, error handling, retry logic, and execution tracking.

## Features

✓ **Automated Scheduling** - Scrapers run on fixed daily schedule  
✓ **24/7 Monitoring** - Continuous background execution  
✓ **Retry Logic** - Automatic retry on failures with exponential backoff  
✓ **Execution Tracking** - Complete history of all scraper runs  
✓ **Comprehensive Logging** - Separate logs for scheduler, scrapers, and errors  
✓ **Statistics Dashboard** - View success rates and performance metrics  
✓ **CLI Management** - Command-line interface to manage and monitor  
✓ **Database Backend** - SQLite for persistent execution history  

## Installation

### 1. Install Dependencies

```bash
cd D:\E-Commerce_Analytics_Project
pip install -r scheduler_requirements.txt
```

### 2. Download Playwright Browsers (one-time)

```bash
python -m playwright install
```

## Quick Start

### Start the Scheduler (Recommended)

```bash
cd ecommerce_analytics_project/data
python cli.py start
```

This starts the scheduler that runs all scrapers on their configured schedules:
- **Myntra**: Daily at 00:00 (midnight)
- **Ajio**: Daily at 02:00
- **Snapdeal**: Daily at 04:00
- **Flipkart**: Daily at 06:00
- **Amazon**: Daily at 08:00

### Run a Scraper Immediately

```bash
python cli.py run myntra
python cli.py run ajio
python cli.py run snapdeal
python cli.py run flipkart
python cli.py run amazon
```

### View Scheduler Status

```bash
python cli.py status
```

**Output:**
```
================================================================================
SCHEDULER STATUS
================================================================================
Running: True
Active jobs: 5

  • Scraper: myntra
    Next run: 2026-08-18 00:00:00+05:30
    Trigger: cron[hour='0', minute='0', ...]

  • Scraper: ajio
    Next run: 2026-08-18 02:00:00+05:30
    Trigger: cron[hour='2', minute='0', ...]
    
  [...]
```

### View Execution Statistics

```bash
python cli.py stats
```

**Output:**
```
================================================================================
SCRAPER EXECUTION STATISTICS
================================================================================

MYNTRA
----------------------------------------
  Total runs: 25
  Successful: 24 (96.0%)
  Failed: 1
  Total products: 12500
  Last run: 2026-08-17 00:15:32

AJIO
----------------------------------------
  Total runs: 25
  Successful: 25 (100.0%)
  Failed: 0
  Total products: 8750
  Last run: 2026-08-17 02:05:18

[...]
```

### View Execution History for a Scraper

```bash
python cli.py history myntra
python cli.py history ajio 20
```

**Output:**
```
====================================================================================================
RECENT EXECUTION HISTORY: MYNTRA
====================================================================================================
Status     Started              Duration     Products   Message
----------------------------------------------------------------------------------------------------
✓ SUCCESS  2026-08-17 00:15:32  385.2s       500        Success
✓ SUCCESS  2026-08-16 00:12:45  372.8s       485        Success
✓ SUCCESS  2026-08-15 00:14:19  389.5s       502        Success
✗ FAILED   2026-08-14 00:16:02  125.3s       0          ConnectionError: Max retries exceeded
✓ SUCCESS  2026-08-13 00:13:58  375.2s       495        Success
====================================================================================================
```

### Clean Up Old Records

```bash
# Delete execution records older than 30 days
python cli.py cleanup 30

# Delete records older than 60 days
python cli.py cleanup 60
```

## Configuration

Edit `config.py` to customize scheduler behavior:

### Modify Schedule Times

```python
SCRAPER_CONFIG = {
    "myntra": {
        "schedule_hour": 0,      # Change hour (0-23)
        "schedule_minute": 0,    # Change minute (0-59)
        "enabled": True,
        # ... other settings
    },
}
```

### Enable/Disable Specific Scrapers

```python
SCRAPER_CONFIG = {
    "myntra": {
        "enabled": True,    # Set to False to disable
        # ...
    },
}
```

### Adjust Retry Behavior

```python
RETRY_CONFIG = {
    "max_retries": 3,          # Number of retry attempts
    "retry_delay": 300,        # Delay in seconds (5 minutes)
    "backoff_factor": 2,       # Exponential backoff multiplier
}
```

### Configure Logging

```python
LOGGING_CONFIG = {
    "level": "INFO",           # DEBUG, INFO, WARNING, ERROR
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
}
```

## File Structure

```
ecommerce_analytics_project/
├── data/
│   ├── config.py                 # Configuration file
│   ├── logger_setup.py           # Logging setup
│   ├── execution_tracker.py      # Execution history tracking
│   ├── scheduler.py              # Main scheduler orchestrator
│   ├── cli.py                    # Command-line interface
│   ├── myntra_scraper.py         # Existing scrapers
│   ├── ajio_scraper.py
│   ├── snapdeal_scraper.py
│   ├── flipkart_scraper.py
│   ├── amazon_scraper.py
│   ├── raw_data/                 # Output CSV files
│   ├── logs/                     # Log files
│   │   ├── scheduler.log
│   │   ├── scraper.log
│   │   └── errors.log
│   └── metadata/
│       └── execution_history.db  # Execution tracking database
```

## Log Files

### scheduler.log
Records scheduler lifecycle events, job scheduling, and status changes.

```
2026-08-17 00:00:00 - scheduler - INFO - Starting scraper: myntra
2026-08-17 00:00:15 - scheduler - INFO - [myntra] ✓ SUCCESS: Scraped 500 products in 385.2s
```

### scraper.log
Detailed logs from scraper execution.

```
2026-08-17 00:00:00 - scraper - INFO - [myntra] Running with keyword='women shirts'
2026-08-17 00:06:25 - scraper - INFO - [myntra] Fetching details 1/500
```

### errors.log
All errors and exceptions from scraper runs.

```
2026-08-14 00:16:00 - errors - ERROR - [myntra] ✗ FAILED after ConnectionError
Traceback (most recent call last):
  File "scheduler.py", line 52, in run_scraper
    ...
```

## Database Schema

### executions table
Tracks individual scraper run details:
- `id`: Unique execution ID
- `scraper_name`: Name of the scraper
- `status`: SUCCESS, FAILED, or RUNNING
- `started_at`: Timestamp when execution started
- `ended_at`: Timestamp when execution ended
- `duration_seconds`: How long the execution took
- `products_scraped`: Number of products scraped
- `error_message`: Error details if failed
- `output_file`: Path to output CSV file

### scraper_stats table
Aggregated statistics per scraper:
- `scraper_name`: Unique scraper identifier
- `total_runs`: Total execution count
- `successful_runs`: Count of successful runs
- `failed_runs`: Count of failed runs
- `last_run_at`: Last execution timestamp
- `total_products_scraped`: Cumulative product count
- `avg_duration_seconds`: Average execution time

## Scheduling Details

### Default Schedule (Staggered to avoid overload)

| Scraper | Time | Rationale |
|---------|------|-----------|
| Myntra  | 00:00 | Start at midnight |
| Ajio    | 02:00 | 2 hours later |
| Snapdeal| 04:00 | 4 hours later |
| Flipkart| 06:00 | 6 hours later |
| Amazon  | 08:00 | 8 hours later |

This staggered schedule prevents overwhelming your network and the target servers.

### Custom Schedule

To run all scrapers at different times, modify `config.py`:

```python
SCRAPER_CONFIG = {
    "myntra": {
        "schedule_hour": 12,    # Noon
        "schedule_minute": 0,
        # ...
    },
    "ajio": {
        "schedule_hour": 13,    # 1 PM
        "schedule_minute": 30,
        # ...
    },
}
```

## Error Handling & Recovery

### Automatic Retry Logic

If a scraper fails:
1. **Retry 1**: After 5 minutes (300 seconds)
2. **Retry 2**: After 10 minutes (300 × 2)
3. **Retry 3**: After 20 minutes (300 × 2²)

After 3 failed attempts, the execution is marked as failed and logged.

### Manual Recovery

If a scraper fails completely:

```bash
# Run immediately to catch up
python cli.py run myntra

# View recent history
python cli.py history myntra 5

# Continue normal schedule
# (scheduler automatically picks up at next scheduled time)
```

## Monitoring

### View Logs in Real Time

**On Windows:**
```bash
# Follow scheduler.log
Get-Content -Path ".\logs\scheduler.log" -Wait

# Follow errors
Get-Content -Path ".\logs\errors.log" -Wait
```

**On Linux/Mac:**
```bash
tail -f logs/scheduler.log
tail -f logs/errors.log
```

### Check Database

```python
from execution_tracker import ExecutionTracker

tracker = ExecutionTracker()

# Get recent runs
runs = tracker.get_recent_runs("myntra", limit=10)
for run in runs:
    print(run)

# Get statistics
stats = tracker.get_stats("myntra")
print(f"Success rate: {stats['successful_runs']}/{stats['total_runs']}")
```

## Troubleshooting

### Scheduler won't start

1. **Check Python path:**
   ```bash
   python --version  # Should be 3.10+
   ```

2. **Verify dependencies:**
   ```bash
   pip install -r scheduler_requirements.txt
   ```

3. **Check logs:**
   ```bash
   type logs\errors.log
   ```

### Scraper runs but doesn't save data

1. **Verify output directory:**
   ```bash
   dir ecommerce_analytics_project\data\raw_data\
   ```

2. **Check file permissions** - Ensure write access to `raw_data/`

3. **View scraper.log for details:**
   ```bash
   type logs\scraper.log
   ```

### Scheduler stops unexpectedly

1. **Check error logs:**
   ```bash
   type logs\errors.log
   ```

2. **Verify no other instance is running:**
   ```bash
   tasklist | findstr python  # Windows
   ps aux | grep python       # Linux/Mac
   ```

3. **Restart the scheduler:**
   ```bash
   python cli.py start
   ```

## Running as a Service (Windows)

To run the scheduler as a Windows service:

### Option 1: Use NSSM (Non-Sucking Service Manager)

```bash
# Download NSSM from https://nssm.cc/
# Extract and navigate to nssm directory

nssm install EcommerceScraper python.exe cli.py start
nssm set EcommerceScraper AppDirectory "D:\E-Commerce_Analytics_Project\ecommerce_analytics_project\data"

# Start the service
nssm start EcommerceScraper

# View service logs
nssm query EcommerceScraper
```

### Option 2: Use Task Scheduler

1. Open Task Scheduler
2. Create Basic Task → Name: "E-Commerce Scraper Scheduler"
3. Trigger → Daily → Time: 00:00
4. Action → Start a program
   - Program: `python.exe`
   - Arguments: `cli.py start`
   - Start in: `D:\E-Commerce_Analytics_Project\ecommerce_analytics_project\data`
5. Click OK

## Running as a Service (Linux/Mac)

### Option 1: systemd (Recommended)

Create `/etc/systemd/system/ecommerce-scraper.service`:

```ini
[Unit]
Description=E-Commerce Scraper Scheduler
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/home/youruser/E-Commerce_Analytics_Project/ecommerce_analytics_project/data
ExecStart=/usr/bin/python3 cli.py start
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable ecommerce-scraper.service
sudo systemctl start ecommerce-scraper.service

# Check status
sudo systemctl status ecommerce-scraper.service
```

### Option 2: cron (Simple Alternative)

```bash
crontab -e
# Add this line:
0 0 * * * cd /path/to/data && python cli.py run myntra
0 2 * * * cd /path/to/data && python cli.py run ajio
```

## Performance Tips

1. **Stagger start times** - Don't run all scrapers at once
2. **Adjust timeouts** - Longer timeouts for slower connections
3. **Monitor disk space** - Old CSV files can accumulate
4. **Clean up logs** - Use `cleanup` command to remove old records

## API Usage (Python)

Use the scheduler programmatically:

```python
from scheduler import ScraperScheduler

# Create scheduler instance
scheduler = ScraperScheduler()

# Start background scheduler
scheduler.start()

# Or run a single scraper manually
scheduler.run_scraper_now("myntra")

# Get status
status = scheduler.get_status()
print(f"Running: {status['running']}")
print(f"Jobs: {status['total_jobs']}")

# Get statistics
stats = scheduler.tracker.get_all_stats()
for stat in stats:
    print(f"{stat['scraper_name']}: {stat['successful_runs']}/{stat['total_runs']} successful")

# Stop gracefully
scheduler.stop()
```

## Support & Debugging

Enable debug logging in `config.py`:

```python
LOGGING_CONFIG = {
    "level": "DEBUG",  # Changed from INFO
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
}
```

Then check detailed logs:
```bash
type logs\scraper.log
```

## License

This scheduler is part of the E-Commerce Analytics Project.

---

**Happy scraping! 🚀**
