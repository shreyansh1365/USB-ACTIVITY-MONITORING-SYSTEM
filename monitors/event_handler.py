from datetime import datetime
import os
import time
import threading

from database.usb_logs import insert_usb_log
from database.transfer_logs import insert_transfer_log
from hashing.sha256 import calculate_sha256


class EventHandler:

    def __init__(self, info):
        self.info = info

        # Stores recently processed events.
        # Key: (action, full_path)
        # Value: timestamp
        self.recent_events = {}

        # Protects recent_events because watchdog callbacks
        # may come from different threads.
        self.event_lock = threading.Lock()

        # Ignore identical events occurring within this many seconds.
        self.debounce_seconds = 2


    def is_duplicate_event(self, action, full_path):

        current_time = time.monotonic()

        # Normalize path so E:\FILE.txt and e:\file.txt
        # are treated as the same Windows path.
        normalized_path = os.path.normcase(
            os.path.abspath(full_path)
        )

        event_key = (action.upper(), normalized_path)

        with self.event_lock:

            previous_time = self.recent_events.get(event_key)

            if previous_time is not None:

                if current_time - previous_time < self.debounce_seconds:
                    return True

            self.recent_events[event_key] = current_time

            # Remove old entries so dictionary does not grow forever.
            expired_keys = [
                key
                for key, timestamp in self.recent_events.items()
                if current_time - timestamp > 60
            ]

            for key in expired_keys:
                self.recent_events.pop(key, None)

        return False


    def process_event(self, action, filename, full_path):

        action = action.upper()

        # Ignore duplicate filesystem notifications.
        if self.is_duplicate_event(action, full_path):

            print(
                f"Duplicate event ignored: "
                f"{action} - {filename}"
            )

            return


        print("=" * 50)
        print("EVENT RECEIVED")
        print(f"Action   : {action}")
        print(f"File     : {filename}")
        print("=" * 50)


        # Save raw USB/file event.
        insert_usb_log(
            datetime.now(),
            self.info["username"],
            self.info["system_name"],
            self.info["drive"],
            self.info["usb_name"],
            self.info["device_id"],
            action,
            self.info["device_code"],
            self.info["mac_address"],
            None
        )

        print("Event saved successfully.")


        # DELETED and RENAMED FROM files may no longer exist.
        # Therefore hashing/transfer logging cannot be performed.
        if not os.path.isfile(full_path):
            return


        # Wait briefly because Windows may still be writing
        # or locking the newly copied file.
        if action in ("CREATED", "MODIFIED"):
            time.sleep(0.5)


        try:
            file_size = round(
                os.path.getsize(full_path) / (1024 * 1024),
                4
            )

        except OSError as error:

            print(f"Could not read file size: {error}")

            return


        try:
            sha256 = calculate_sha256(full_path)

        except Exception as error:

            print(f"SHA256 calculation failed: {error}")

            sha256 = None


        insert_transfer_log(
            datetime.now(),
            self.info["username"],
            self.info["system_name"],
            self.info["device_code"],
            action,
            filename,
            file_size,
            sha256
        )

        print("Transfer log saved successfully.")