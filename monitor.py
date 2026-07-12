from database.permissions import check_permission
from database.access_requests import create_access_request
import threading
import time
from datetime import datetime

from database.usb_logs import insert_usb_log
from monitors.directory_monitor import DirectoryMonitor
from usb.detector import get_connected_usb
from usb.device_info import get_device_info


def save_usb_event(info, event_type, duration_seconds=None):
    insert_usb_log(
        datetime.now(),
        info["username"],
        info["system_name"],
        info["drive"],
        info["usb_name"],
        info["device_id"],
        event_type,
        info["device_code"],
        info["mac_address"],
        duration_seconds,
    )


def start_directory_monitor(info):
    monitor = DirectoryMonitor(info)
    thread = threading.Thread(target=monitor.start, daemon=True)
    thread.start()


def main():
    print("=" * 60)
    print("USB Monitor Version 2 Started")
    print("=" * 60)

    previous = {}
    active_info = {}
    connected_at = {}

    while True:
        try:
            current = get_connected_usb()
        except Exception as error:
            print(f"USB Detection Error: {error}")
            time.sleep(2)
            continue

        inserted_drives = current.keys() - previous.keys()
        removed_drives = previous.keys() - current.keys()

        for drive in inserted_drives:
            try:
                info = get_device_info(current[drive])

                permission = check_permission(info["device_code"])

                if permission == "ALLOWED":
                    active_info[drive] = info
                    connected_at[drive] = datetime.now()

                    save_usb_event(info, "CONNECTED")

                    start_directory_monitor(info)

                    print(f"USB Allowed: {info['usb_name']} ({drive})")


                elif permission == "BLOCKED":

                    save_usb_event(info, "BLOCKED")

                    print(f"USB BLOCKED: {info['usb_name']} ({drive})")


                else:

                    create_access_request(
                    device_code=info["device_code"],
                    serial_number=info["device_id"],
                    device_name=info["usb_name"],
                    username=info["username"],
                    system_name=info["system_name"],
                    drive_letter=info["drive"],
                    filesystem=info["filesystem"]
                    )

                    print(f"USB Pending Approval: {info['usb_name']} ({drive})")
            except Exception as error:
                print(f"USB connection handling failed for {drive}: {error}")

        for drive in removed_drives:
            info = active_info.pop(drive, None)
            started = connected_at.pop(drive, None)
            if not info:
                print(f"USB Removed: {drive} (device details unavailable)")
                continue
            try:
                duration = int((datetime.now() - started).total_seconds()) if started else None
                save_usb_event(info, "REMOVED", duration)
                print(f"USB Removed: {info['usb_name']} ({drive})")
            except Exception as error:
                print(f"USB removal handling failed for {drive}: {error}")

        previous = current
        time.sleep(2)


if __name__ == "__main__":
    main()
