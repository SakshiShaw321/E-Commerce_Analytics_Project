# Quick Start Guide - 5 Minutes to Automated Scraping

## Installation (2 minutes)

### 1. Install Dependencies
```bash
cd D:\E-Commerce_Analytics_Project
pip install -r scheduler_requirements.txt
```

### 2. Setup Playwright (1 minute, one-time only)
```bash
python -m playwright install
```

## Start Scraping (1 minute)

### Run the Scheduler
```bash
cd ecommerce_analytics_project\data
python cli.py start
```

**That's it!** The scheduler will now:
- Run Myntra scraper every day at 00:00 (midnight)
- Run Ajio scraper every day at 02:00
- Run Snapdeal scraper every day at 04:00
- Run Flipkart scraper every day at 06:00
- Run Amazon scraper every day at 08:00

Keep this terminal open. The scheduler runs in the background.

## Monitoring (1 minute)

Open another terminal and run:

### Check Scheduler Status
```bash
python cli.py status
```

### View Statistics
```bash
python cli.py stats
```

### Run a Scraper Now (Don't Wait for Schedule)
```bash
python cli.py run myntra
python cli.py run ajio
python cli.py run snapdeal
python cli.py run flipkart
python cli.py run amazon
```

### View Recent Runs
```bash
python cli.py history myntra
python cli.py history ajio 20
```

## Done! 🎉

Your scrapers now run automatically every 24 hours with:
- ✓ Error handling and automatic retries
- ✓ Complete execution history tracking
- ✓ Detailed logging of every run
- ✓ Production-ready reliability

## What Gets Created

Each day, these files are saved to `ecommerce_analytics_project/data/raw_data/`:
- `myntra_women_shirts_raw.csv` - Myntra products
- `ajio_women_shirts_raw.csv` - Ajio products
- `snapdeal_women_shirts_raw.csv` - Snapdeal products
- `flipkart_women_shirts_raw.csv` - Flipkart products
- `amazon_women_shirts_raw.csv` - Amazon products

## View Logs

Check what happened:
```bash
# Scheduler logs
type logs\scheduler.log

# Scraper details
type logs\scraper.log

# Error details
type logs\errors.log
```

## Customize Schedule

Edit `config.py` to change times:

```python
SCRAPER_CONFIG = {
    "myntra": {
        "schedule_hour": 0,      # Change hour (0-23)
        "schedule_minute": 0,    # Change minute
    },
}
```

Then restart scheduler (Ctrl+C → python cli.py start)

## Common Commands

```bash
# Start scheduler
python cli.py start

# Run scraper immediately
python cli.py run myntra

# Check status
python cli.py status

# View statistics
python cli.py stats

# View last 10 runs
python cli.py history myntra

# View last 20 runs
python cli.py history ajio 20

# Clean database (older than 30 days)
python cli.py cleanup 30

# Help
python cli.py help
```

## Next Steps

- **Want more details?** Read `SCHEDULER_README.md`
- **Need setup help?** Read `SETUP_INSTRUCTIONS.md`
- **Change settings?** Edit `config.py`
- **Keep it running 24/7?** Set up Windows Service (see SCHEDULER_README.md)

---

**Questions?** Check the logs in `logs/` folder for detailed error messages.
