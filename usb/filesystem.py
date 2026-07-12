import win32api


def get_filesystem(drive):

    try:
        info = win32api.GetVolumeInformation(drive)

        return info[4]

    except Exception:
        return None


if __name__ == "__main__":

    drive = input("Enter Drive (Example E:\\): ")

    fs = get_filesystem(drive)

    print("Filesystem:", fs)