from database.db import get_connection


def insert_usb_log(
    event_time,
    username,
    system_name,
    drive_letter,
    usb_name,
    device_id,
    event_type,
    device_code,
    mac_address,
    duration_seconds=None
):

    conn = get_connection()
    cursor = conn.cursor()

    query = """
    INSERT INTO usb_logs
    (
        event_time,
        username,
        system_name,
        drive_letter,
        usb_name,
        device_id,
        event_type,
        device_code,
        mac_address,
        duration_seconds
    )
    VALUES
    (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """

    cursor.execute(
        query,
        (
            event_time,
            username,
            system_name,
            drive_letter,
            usb_name,
            device_id,
            event_type,
            device_code,
            mac_address,
            duration_seconds
        )
    )

    conn.commit()

    cursor.close()
    conn.close()