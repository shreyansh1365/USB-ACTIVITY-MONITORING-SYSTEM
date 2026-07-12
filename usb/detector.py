import wmi
import time

c = wmi.WMI()

previous = {}

def get_connected_usb():
    devices = {}

    try:

        for disk in c.Win32_DiskDrive():
            if "USB" not in disk.InterfaceType:
                continue

            for partition in disk.associators("Win32_DiskDriveToDiskPartition"):
                for logical in partition.associators("Win32_LogicalDiskToPartition"):

                    devices[logical.DeviceID + "\\"] = {
                        "drive": logical.DeviceID + "\\",
                        "name": disk.Caption,
                        "device_id": disk.PNPDeviceID
                    }

        return devices
    
    except Exception:
        return {}


if __name__ == "__main__":

    print("Waiting for USB...")

    while True:

        current = get_connected_usb()

        # Inserted
        for drive in current:
            if drive not in previous:
                print("\nUSB INSERTED")
                print(current[drive])

        # Removed
        for drive in previous:
            if drive not in current:
                print("\nUSB REMOVED")
                print(previous[drive])

        previous = current

        time.sleep(1)