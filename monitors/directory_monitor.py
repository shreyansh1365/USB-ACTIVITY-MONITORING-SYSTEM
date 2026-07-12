import win32file
import win32con
import os

from monitors.event_handler import EventHandler


class DirectoryMonitor:

    def __init__(self, info):

        self.info = info

        self.drive = info["drive"]

        self.handle = None

        self.event_handler = EventHandler(info)

    def start(self):

        self.handle = win32file.CreateFile(

            self.drive,

            0x0001,

            win32con.FILE_SHARE_READ
            |
            win32con.FILE_SHARE_WRITE
            |
            win32con.FILE_SHARE_DELETE,

            None,

            win32con.OPEN_EXISTING,

            win32con.FILE_FLAG_BACKUP_SEMANTICS,

            None

        )

        print(f"Monitoring Started : {self.drive}")

        while True:

            results = win32file.ReadDirectoryChangesW(

                self.handle,

                65536,

                True,

                win32con.FILE_NOTIFY_CHANGE_FILE_NAME
                | win32con.FILE_NOTIFY_CHANGE_DIR_NAME
                | win32con.FILE_NOTIFY_CHANGE_ATTRIBUTES
                | win32con.FILE_NOTIFY_CHANGE_SIZE
                | win32con.FILE_NOTIFY_CHANGE_LAST_WRITE
                | win32con.FILE_NOTIFY_CHANGE_SECURITY,

                None,

                None

            )

            for action, filename in results:

                full_path = os.path.join(self.drive, filename)

                if action == 1:
                    self.event_handler.process_event("CREATED", filename, full_path)

                elif action == 2:
                    self.event_handler.process_event("DELETED", filename, full_path)

                elif action == 3:
                    self.event_handler.process_event("MODIFIED", filename, full_path)

                elif action == 4:
                    self.event_handler.process_event("RENAMED FROM", filename, full_path)

                elif action == 5:
                    self.event_handler.process_event("RENAMED TO", filename, full_path)

                else:
                    print(action, filename)