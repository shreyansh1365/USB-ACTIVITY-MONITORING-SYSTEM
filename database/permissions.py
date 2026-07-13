from database.db import get_connection
from database.access_requests import (
    get_latest_approved_request,
    expire_request,
)


DURATION_ACTIONS = {
    10: "ALLOW_10_MIN",
    30: "ALLOW_30_MIN",
    60: "ALLOW_1_HOUR",
}


def _log_history(cursor, request_id, device_code, action, admin_name, notes=None):
    cursor.execute(
        """
        INSERT INTO approval_history
        (request_id, device_code, admin_name, action, notes)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (request_id, device_code, admin_name, action, notes),
    )


def get_policy(device_code):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT policy FROM access_policy WHERE device_code = %s",
        (device_code,),
    )

    row = cursor.fetchone()

    cursor.close()
    conn.close()

    return row["policy"] if row else None


def set_policy(device_code, policy):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO access_policy (device_code, policy)
        VALUES (%s, %s)
        ON CONFLICT (device_code)
        DO UPDATE SET policy = EXCLUDED.policy
        """,
        (device_code, policy),
    )

    conn.commit()
    cursor.close()
    conn.close()


def is_device_trusted(device_code):
    return get_policy(device_code) == "ALLOW"


def is_device_blocked(device_code):
    return get_policy(device_code) == "BLOCK"


def approve_device(
    device_code,
    serial_number,
    device_name,
    admin,
    request_id=None,
    duration_minutes=None,
):
    conn = get_connection()
    cursor = conn.cursor()

    permanent = duration_minutes not in DURATION_ACTIONS
    action = "ALLOW" if permanent else DURATION_ACTIONS[duration_minutes]

    if permanent:
        cursor.execute(
            """
            INSERT INTO trusted_devices
            (device_code, serial_number, device_name, approved_by)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (device_code)
            DO UPDATE SET
                serial_number = EXCLUDED.serial_number,
                device_name = EXCLUDED.device_name,
                approved_by = EXCLUDED.approved_by
            """,
            (device_code, serial_number, device_name, admin),
        )

    cursor.execute(
        """
        INSERT INTO access_policy (device_code, policy)
        VALUES (%s, 'ALLOW')
        ON CONFLICT (device_code)
        DO UPDATE SET policy = 'ALLOW'
        """,
        (device_code,),
    )

    if request_id is not None:
        if permanent:
            cursor.execute(
                """
                UPDATE usb_access_requests
                SET status = 'APPROVED',
                    approved_by = %s,
                    approval_time = NOW(),
                    approved_until = NULL
                WHERE id = %s
                """,
                (admin, request_id),
            )
        else:
            cursor.execute(
                """
                UPDATE usb_access_requests
                SET status = 'APPROVED',
                    approved_by = %s,
                    approval_time = NOW(),
                    approved_until = NOW() + (%s * INTERVAL '1 minute')
                WHERE id = %s
                """,
                (admin, duration_minutes, request_id),
            )

    notes = (
        "Always Trust"
        if permanent
        else f"Temporary access for {duration_minutes} minutes"
    )

    _log_history(
        cursor,
        request_id,
        device_code,
        action,
        admin,
        notes,
    )

    conn.commit()
    cursor.close()
    conn.close()


def block_device(
    device_code,
    serial_number,
    admin,
    reason,
    request_id=None,
):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO blocked_devices
        (device_code, serial_number, blocked_by, reason)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (device_code)
        DO UPDATE SET
            serial_number = EXCLUDED.serial_number,
            blocked_by = EXCLUDED.blocked_by,
            reason = EXCLUDED.reason
        """,
        (device_code, serial_number, admin, reason),
    )

    cursor.execute(
        """
        INSERT INTO access_policy (device_code, policy)
        VALUES (%s, 'BLOCK')
        ON CONFLICT (device_code)
        DO UPDATE SET policy = 'BLOCK'
        """,
        (device_code,),
    )

    if request_id is not None:
        cursor.execute(
            """
            UPDATE usb_access_requests
            SET status = 'BLOCKED',
                approved_by = %s,
                approval_time = NOW(),
                approved_until = NULL
            WHERE id = %s
            """,
            (admin, request_id),
        )

    _log_history(
        cursor,
        request_id,
        device_code,
        "BLOCK",
        admin,
        reason,
    )

    conn.commit()
    cursor.close()
    conn.close()


def list_trusted_devices():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM trusted_devices ORDER BY approved_on DESC"
    )

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    return rows


def list_blocked_devices():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM blocked_devices ORDER BY blocked_on DESC"
    )

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    return rows


def remove_trust(device_code, admin):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM trusted_devices WHERE device_code = %s",
        (device_code,),
    )

    cursor.execute(
        """
        INSERT INTO access_policy (device_code, policy)
        VALUES (%s, 'ASK_ADMIN')
        ON CONFLICT (device_code)
        DO UPDATE SET policy = 'ASK_ADMIN'
        """,
        (device_code,),
    )

    conn.commit()
    cursor.close()
    conn.close()


def unblock_device(device_code, admin):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM blocked_devices WHERE device_code = %s",
        (device_code,),
    )

    cursor.execute(
        """
        INSERT INTO access_policy (device_code, policy)
        VALUES (%s, 'ASK_ADMIN')
        ON CONFLICT (device_code)
        DO UPDATE SET policy = 'ASK_ADMIN'
        """,
        (device_code,),
    )

    conn.commit()
    cursor.close()
    conn.close()


def check_permission(device_code):
    policy = get_policy(device_code)

    if policy == "BLOCK":
        return "BLOCKED"

    if policy == "ALLOW":
        latest = get_latest_approved_request(device_code)
        approved_until = latest.get("approved_until") if latest else None

        if approved_until is None:
            return "ALLOWED"

        if approved_until <= _now():
            expire_request(latest["id"])
            set_policy(device_code, "ASK_ADMIN")
            return "EXPIRED"

        return "ALLOWED"

    return "PENDING"


def _now():
    from datetime import datetime
    return datetime.now()