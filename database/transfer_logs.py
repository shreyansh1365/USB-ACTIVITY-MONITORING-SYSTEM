from database.db import get_connection


def insert_transfer_log(
    event_time,
    username,
    system_name,
    device_code,
    direction,
    file_name,
    file_size_mb,
    sha256
):
    conn = get_connection()
    cursor = conn.cursor()

    query = """
    INSERT INTO transfer_logs
    (
        event_time,
        username,
        system_name,
        device_code,
        direction,
        file_name,
        file_size_mb,
        sha256
    )
    VALUES
    (%s,%s,%s,%s,%s,%s,%s,%s)
    """

    cursor.execute(
        query,
        (
            event_time,
            username,
            system_name,
            device_code,
            direction,
            file_name,
            file_size_mb,
            sha256
        )
    )

    conn.commit()
    cursor.close()
    conn.close()