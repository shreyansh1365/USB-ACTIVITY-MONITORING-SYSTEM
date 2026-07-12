from database.db import get_connection


def get_device_code(device_id):
    """
    Returns the existing device code if the USB is already registered.
    Otherwise creates a new device code and stores it.
    """

    conn = get_connection()
    cursor = conn.cursor()

    # Check if device already exists
    cursor.execute(
        "SELECT device_code FROM device_registry WHERE device_id=%s",
        (device_id,)
    )

    row = cursor.fetchone()

    if row:
        cursor.close()
        conn.close()
        return row[0]

    # Get latest device code
    cursor.execute(
        "SELECT device_code FROM device_registry ORDER BY device_code DESC LIMIT 1"
    )

    last = cursor.fetchone()

    if last:
        number = int(last[0][3:]) + 1
    else:
        number = 1

    new_code = f"DEV{number:03d}"

    cursor.execute(
        """
        INSERT INTO device_registry(device_code, device_id)
        VALUES(%s,%s)
        """,
        (new_code, device_id)
    )

    conn.commit()

    cursor.close()
    conn.close()

    return new_code