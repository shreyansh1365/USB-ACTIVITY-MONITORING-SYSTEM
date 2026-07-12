from database.db import get_connection
from database.access_requests import (
    get_latest_approved_request,
    expire_request,
)


# Maps a duration in minutes to the matching approval_history.action enum value.
# Anything else (None / 0 / not in this map) is treated as a permanent approval.
DURATION_ACTIONS = {
    10: "ALLOW_10_MIN",
    30: "ALLOW_30_MIN",
    60: "ALLOW_1_HOUR",
}


def _log_history(cursor, request_id, device_code, action, admin_name, notes=None):
    """Append a row to approval_history using the caller's cursor, so the log
    write is part of the same transaction as the permission change.
    `action` must be one of approval_history's ENUM values
    ('ALLOW','BLOCK','ALLOW_10_MIN','ALLOW_30_MIN','ALLOW_1_HOUR')."""
    cursor.execute(
        """
        INSERT INTO approval_history
        (request_id, device_code, admin_name, action, notes)
        VALUES (%s,%s,%s,%s,%s)
        """,
        (request_id, device_code, admin_name, action, notes)
    )


def get_policy(device_code):
    """Returns 'ALLOW' / 'BLOCK' / 'ASK_ADMIN', or None if the device has
    never been seen by access_policy yet."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT policy FROM access_policy WHERE device_code=%s",
        (device_code,)
    )

    row = cursor.fetchone()

    cursor.close()
    conn.close()

    return row[0] if row else None


def set_policy(device_code, policy):
    """Upserts the effective policy for a device_code."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO access_policy (device_code, policy)
        VALUES (%s,%s)
        ON DUPLICATE KEY UPDATE policy=VALUES(policy)
        """,
        (device_code, policy)
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
    """Approves a device.
    duration_minutes=None -> permanent trust (written to trusted_devices).
    duration_minutes=10/30/60 -> temporary grant (approved_until on the
    request row, access_policy still flips to ALLOW so the running monitor
    picks it up, but nothing is written to trusted_devices)."""

    conn = get_connection()
    cursor = conn.cursor()

    permanent = duration_minutes not in DURATION_ACTIONS
    action = "ALLOW" if permanent else DURATION_ACTIONS[duration_minutes]

    if permanent:
        cursor.execute(
            """
            INSERT INTO trusted_devices
            (device_code, serial_number, device_name, approved_by)
            VALUES (%s,%s,%s,%s)
            """,
            (device_code, serial_number, device_name, admin)
        )

    cursor.execute(
        """
        INSERT INTO access_policy (device_code, policy)
        VALUES (%s,'ALLOW')
        ON DUPLICATE KEY UPDATE policy='ALLOW'
        """,
        (device_code,)
    )

    if request_id is not None:
        if permanent:
            cursor.execute(
                """
                UPDATE usb_access_requests
                SET status='APPROVED', approved_by=%s, approval_time=NOW(), approved_until=NULL
                WHERE id=%s
                """,
                (admin, request_id)
            )
        else:
            # approved_until is computed in SQL (DATE_ADD) so it's always in
            # sync with the DB server's clock, not this machine's clock.
            cursor.execute(
                """
                UPDATE usb_access_requests
                SET status='APPROVED', approved_by=%s, approval_time=NOW(),
                    approved_until=DATE_ADD(NOW(), INTERVAL %s MINUTE)
                WHERE id=%s
                """,
                (admin, duration_minutes, request_id)
            )

    notes = "Always Trust" if permanent else f"Temporary access for {duration_minutes} minutes"
    _log_history(cursor, request_id, device_code, action, admin, notes)

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
        VALUES (%s,%s,%s,%s)
        """,
        (device_code, serial_number, admin, reason)
    )

    cursor.execute(
        """
        INSERT INTO access_policy (device_code, policy)
        VALUES (%s,'BLOCK')
        ON DUPLICATE KEY UPDATE policy='BLOCK'
        """,
        (device_code,)
    )

    if request_id is not None:
        cursor.execute(
            """
            UPDATE usb_access_requests
            SET status='BLOCKED', approved_by=%s, approval_time=NOW(), approved_until=NULL
            WHERE id=%s
            """,
            (admin, request_id)
        )

    _log_history(cursor, request_id, device_code, "BLOCK", admin, reason)

    conn.commit()

    cursor.close()
    conn.close()


def list_trusted_devices():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM trusted_devices ORDER BY approved_on DESC")
    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    return rows


def list_blocked_devices():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM blocked_devices ORDER BY blocked_on DESC")
    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    return rows


def remove_trust(device_code, admin):
    """Revokes permanent trust: removes from trusted_devices and resets the
    policy to ASK_ADMIN, so the device goes through approval again next time.
    Note: approval_history's action ENUM has no 'TRUST_REMOVED' value, so this
    action isn't written to the audit log unless you extend that ENUM
    (see database/schema_access_control_v2.sql)."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM trusted_devices WHERE device_code=%s", (device_code,))
    cursor.execute(
        """
        INSERT INTO access_policy (device_code, policy)
        VALUES (%s,'ASK_ADMIN')
        ON DUPLICATE KEY UPDATE policy='ASK_ADMIN'
        """,
        (device_code,)
    )

    # Uncomment after running database/schema_access_control_v2.sql:
    # _log_history(cursor, None, device_code, "TRUST_REMOVED", admin)

    conn.commit()

    cursor.close()
    conn.close()


def unblock_device(device_code, admin):
    """Removes a device from blocked_devices and resets the policy to
    ASK_ADMIN. See the note on remove_trust() re: approval_history's ENUM."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM blocked_devices WHERE device_code=%s", (device_code,))
    cursor.execute(
        """
        INSERT INTO access_policy (device_code, policy)
        VALUES (%s,'ASK_ADMIN')
        ON DUPLICATE KEY UPDATE policy='ASK_ADMIN'
        """,
        (device_code,)
    )

    # Uncomment after running database/schema_access_control_v2.sql:
    # _log_history(cursor, None, device_code, "UNBLOCKED", admin)

    conn.commit()

    cursor.close()
    conn.close()


def check_permission(device_code):
    """Returns 'ALLOWED', 'BLOCKED', 'EXPIRED', or 'PENDING'.

    'EXPIRED' means a temporary grant just ran out: the caller (monitor.py)
    should stop monitoring this drive immediately, even mid-session. The
    device falls back to ASK_ADMIN, so it needs a fresh approval the next
    time it's inserted."""

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
