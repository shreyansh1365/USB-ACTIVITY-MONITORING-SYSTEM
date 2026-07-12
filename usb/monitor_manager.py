from usb.filesystem import get_filesystem


def get_monitor(drive):

    fs = get_filesystem(drive)

    if fs == "NTFS":
        return "USN"

    elif fs in ["FAT32", "exFAT"]:
        return "DIRECTORY"

    else:
        return None