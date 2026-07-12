from monitors.directory_monitor import DirectoryMonitor

drive = input("Drive : ")

monitor = DirectoryMonitor(drive)

monitor.start()