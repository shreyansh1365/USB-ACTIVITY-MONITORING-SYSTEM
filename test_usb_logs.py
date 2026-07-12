from database.usb_logs import insert_usb_log

from datetime import datetime

insert_usb_log(
    datetime.now(),
    "SHREYANSH",
    "LAPTOP",
    "E:\\",
    "SanDisk",
    "USBSTOR\\TEST",
    "INSERTED",
    "DEV001",
    "AA-BB-CC-DD",
    None
)

print("Inserted Successfully")