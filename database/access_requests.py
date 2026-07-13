from database.db import get_connection


def create_access_request(
    device_code,
    serial_number,
    device_name,
    username,
    system_name,
    drive_letter,
    filesystem
):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO usb_access_requests
        (
            device_code,
            serial_number,
            device_name,
            username,
            system_name,
            drive_letter,
            filesystem,
            status
        )
        VALUES
        (%s,%s,%s,%s,%s,%s,%s,'PENDING')
        """,
        (
            device_code,
            serial_number,
            device_name,
            username,
            system_name,
            drive_letter,
            filesystem
        )
    )

    conn.commit()

    cursor.close()
    conn.close()


def pending_requests():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM usb_access_requests
        WHERE status='PENDING'
        ORDER BY request_time DESC
        """
    )

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    return rows


def get_request_by_id(request_id):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM usb_access_requests
        WHERE id=%s
        """,
        (request_id,)
    )

    row = cursor.fetchone()

    cursor.close()
    conn.close()

    return row


def has_pending_request(device_code):
    """True if this device already has an un-actioned PENDING request,
    so we don't spam usb_access_requests with a new row every time the
    same still-undecided USB is unplugged and replugged."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id FROM usb_access_requests
        WHERE device_code=%s AND status='PENDING'
        LIMIT 1
        """,
        (device_code,)
    )

    row = cursor.fetchone()

    cursor.close()
    conn.close()

    return row is not None


def finalize_request(request_id, status, approved_by=None, approved_until=None, remarks=None):
    """Updates a request with the admin's decision: status, who decided it,
    when, and (for temporary approvals) when it expires."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE usb_access_requests
        SET status=%s,
            approved_by=%s,
            approval_time=CURRENT_TIMESTAMP,
            approved_until=%s,
            remarks=%s
        WHERE id=%s
        """,
        (status, approved_by, approved_until, remarks, request_id)
    )

    conn.commit()

    cursor.close()
    conn.close()


def get_latest_approved_request(device_code):
    """Most recent APPROVED request for this device — used to look up
    approved_until when checking whether a temporary grant has expired."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT * FROM usb_access_requests
        WHERE device_code=%s AND status='APPROVED'
        ORDER BY approval_time DESC
        LIMIT 1
        """,
        (device_code,)
    )

    row = cursor.fetchone()

    cursor.close()
    conn.close()

    return row


def expire_request(request_id):
    """Marks a request EXPIRED once its approved_until has passed."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE usb_access_requests SET status='EXPIRED' WHERE id=%s",
        (request_id,)
    )

    conn.commit()

    cursor.close()
    conn.close()


def update_request_status(
    request_id,
    status
):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE usb_access_requests
        SET status=%s
        WHERE id=%s
        """,
        (
            status,
            request_id
        )
    )

    conn.commit()

    cursor.close()
    conn.close()