from database.device_registry import get_device_code

device_id = input("Enter Device ID:\n")

code = get_device_code(device_id)

print("Device Code:", code)