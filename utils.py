#!/usr/bin/env python3
import os, json, logging, subprocess
from datetime import datetime
from database import DownloadDB


def setup_logging():
    os.makedirs("logs", exist_ok=True)
    log_file = f"logs/scraper_{datetime.now().strftime('%Y%m%d')}.log"
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
                       handlers=[logging.FileHandler(log_file), logging.StreamHandler()])
    return logging.getLogger(__name__)


def load_config():
    config_file = "config.json"
    default = {"delay_min": 3, "delay_max": 10, "posts_per_profile": 15, "max_retries": 3,
               "session_timeout": 3600, "log_level": "INFO", "auto_mode": False, "auto_interval": 3600,
               "max_downloads_per_day": 500}
    if os.path.exists(config_file):
        with open(config_file, 'r') as f:
            config = json.load(f)
            for k, v in default.items():
                if k not in config: config[k] = v
            return config
    with open(config_file, 'w') as f:
        json.dump(default, f, indent=2)
    return default


def get_system_info():
    db = DownloadDB()
    stats = db.get_stats()
    try:
        device = subprocess.check_output(['uname', '-m']).decode().strip()
        device = 'Android (ARM64)' if 'aarch64' in device else 'Android (ARM)' if 'arm' in device else 'Termux'
    except:
        device = 'Termux'
    return {'device': device, 'storage': stats['disk_usage'], 'downloads': stats['total']}


def get_top_profiles(limit=10):
    return DownloadDB().get_top_profiles(limit)


def get_downloads_by_day(days=7):
    return DownloadDB().get_downloads_by_day(days)


def get_performance_stats():
    return DownloadDB().get_performance_stats()
