"""Configuration for the automated scraper scheduler."""

import os
from pathlib import Path
from datetime import datetime, time

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "raw_data"
LOGS_DIR = BASE_DIR / "logs"
DB_DIR = BASE_DIR / "metadata"

DATA_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)
DB_DIR.mkdir(exist_ok=True)

SCRAPER_CONFIG = {
    "myntra": {
        "module": "myntra_scraper",
        "function": "scrape_myntra_women_shirts",
        "output_file": DATA_DIR / "ecommerce_myntra_data.csv",
        "enabled": True,
        "schedule_hour": 10,
        "schedule_minute": 0,
        "max_products": None,
        "max_pages": None,
        "search_only": True,
        "keyword": "women shirts",
    },
    "ajio": {
        "module": "ajio_scraper",
        "function": "scrape_ajio_women_shirts",
        "output_file": DATA_DIR / "ecommerce_ajio_data.csv",
        "enabled": True,
        "schedule_hour": 10,
        "schedule_minute": 0,
        "max_products": None,
        "max_pages": None,
        "search_only": True,
        "keyword": "women shirts",
    },
    "snapdeal": {
        "module": "snapdeal_scraper",
        "function": "scrape_snapdeal_women_shirts",
        "output_file": DATA_DIR / "ecommerce_snapdeal_data.csv",
        "enabled": True,
        "schedule_hour": 10,
        "schedule_minute": 0,
        "max_products": None,
        "max_pages": None,
        "search_only": True,
        "keyword": "women shirts",
    },
    "flipkart": {
        "module": "flipkart_scraper",
        "function": "scrape_flipkart_women_shirts",
        "output_file": DATA_DIR / "ecommerce_flipkart_data.csv",
        "enabled": True,
        "schedule_hour": 10,
        "schedule_minute": 0,
        "max_products": None,
        "max_pages": None,
        "search_only": True,
        "keyword": "women shirts",
    },
    "amazon": {
        "module": "amazon_scraper",
        "function": "scrape_amazon_women_shirts",
        "output_file": DATA_DIR / "ecommerce_amazon_data.csv",
        "enabled": True,
        "schedule_hour": 10,
        "schedule_minute": 0,
        "max_products": None,
        "max_pages": None,
        "search_only": True,
        "keyword": "women shirts",
    },
}

SCHEDULER_CONFIG = {
    "timezone": "Asia/Kolkata",
    "executor_type": "threadpool",
    "max_workers": 1,
    "job_defaults": {
        "coalesce": True,
        "max_instances": 1,
    },
}

LOGGING_CONFIG = {
    "level": "INFO",
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    "date_format": "%Y-%m-%d %H:%M:%S",
}

RETRY_CONFIG = {
    "max_retries": 3,
    "retry_delay": 300,
    "backoff_factor": 2,
}

NOTIFICATION_CONFIG = {
    "send_email": False,
    "email_recipients": [],
    "send_to_slack": False,
    "slack_webhook": "",
}
