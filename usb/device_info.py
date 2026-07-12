import socket
import getpass
import uuid

from usb.filesystem import get_filesystem
from database.device_registry import get_device_code


def get_mac():
    mac = uuid.getnode()
    return ":".join(f"{(mac >> ele) & 0xff:02X}" for ele in range(40, -8, -8))


def get_device_info(device):

    info = {}

    info["username"] = getpass.getuser()
    info["system_name"] = socket.gethostname()
    info["mac_address"] = get_mac()

    info["drive"] = device["drive"]
    info["usb_name"] = device["name"]
    info["device_id"] = device["device_id"]

    info["filesystem"] = get_filesystem(device["drive"])

    info["device_code"] = get_device_code(device["device_id"])

    return info