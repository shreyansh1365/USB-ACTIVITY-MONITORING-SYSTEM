from usb.detector import get_connected_usb
from usb.monitor_manager import get_monitor

devices = get_connected_usb()

if not devices:

    print("No USB")

else:

    drive = list(devices.keys())[0]

    print("Drive :", drive)

    print("Monitor :", get_monitor(drive))