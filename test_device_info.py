from usb.detector import get_connected_usb
from usb.device_info import get_device_info

devices = get_connected_usb()

if not devices:
    print("No USB Found")
else:
    drive = list(devices.keys())[0]

    info = get_device_info(devices[drive])

    print("\nUSB Information\n")

    for k, v in info.items():
        print(f"{k} : {v}")