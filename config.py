import os
from dotenv import load_dotenv

load_dotenv()
# ==========================
# Database Configuration
# ==========================

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "usb_monitor"),
}


# ==========================
# Monitoring Settings
# ==========================

SCAN_INTERVAL = 1          # Seconds


# ==========================
# Logging
# ==========================

LOG_FILE = "logs/monitor.log"


# ==========================
# Hash Algorithm
# ==========================

HASH_ALGORITHM = "sha256"


# ==========================
# Device Code Prefix
# ==========================

DEVICE_PREFIX = "DEV"


# ==========================
# Supported File Systems
# ==========================

SUPPORTED_FILESYSTEMS = [
    "NTFS",
    "FAT32",
    "exFAT"
]