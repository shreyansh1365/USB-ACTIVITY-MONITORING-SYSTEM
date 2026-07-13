"""Flask dashboard and reporting API for USB Sentinel."""

import csv
import io
import os
import re
import zipfile
from datetime import datetime, timedelta
from html import escape as xml_escape

import psycopg2
from psycopg2.extras import RealDictCursor

from flask import Flask, Response, jsonify, render_template, request

from config import DB_CONFIG
from database.access_requests import (
    pending_requests,
    get_request_by_id,
)
from database.permissions import (
    approve_device,
    block_device,
    list_trusted_devices,
    list_blocked_devices,
    remove_trust,
    unblock_device,
)

try:
    from usb.filesystem import get_filesystem as read_filesystem
except (ImportError, OSError):
    read_filesystem = None


app = Flask(__name__)
@app.route("/api/debug/time")
def debug_time():
    db_time = query(
        "SELECT NOW() AS db_now, CURRENT_DATE AS db_date",
        fetchone=True,
    )

    return jsonify({
        "python_now": str(datetime.now()),
        "db_now": str(db_time["db_now"]),
        "db_date": str(db_time["db_date"]),
    })


def get_connection():
    return psycopg2.connect(
        os.environ["DATABASE_URL"],
        cursor_factory=RealDictCursor
    )


def query(sql, params=None, fetchone=False):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(sql, params or ())
        return cursor.fetchone() if fetchone else cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def fmt_rows(rows, time_field="event_time"):
    for row in rows:
        value = row.get(time_field)
        if hasattr(value, "strftime"):
            row[time_field] = value.strftime("%Y-%m-%d %H:%M:%S")
    return rows


def fmt_all_datetimes(rows):
    """Formats every datetime-like value in each row. Used for access-control
    endpoints, whose rows can have several datetime columns at once
    (request_time, approval_time, approved_until)."""
    for row in rows:
        for key, value in row.items():
            if hasattr(value, "strftime"):
                row[key] = value.strftime("%Y-%m-%d %H:%M:%S")
    return rows


def safe_limit(default=10, maximum=200):
    try:
        return max(1, min(int(request.args.get("limit", default)), maximum))
    except (TypeError, ValueError):
        return default


def filters_from_request():
    period = request.args.get("period", "7d").strip().lower()
    if period not in {"today", "7d", "month", "all"}:
        period = "7d"

    date_value = request.args.get("date", "").strip()
    if date_value and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_value):
        date_value = ""

    return {
        "period": period,
        "usb": request.args.get("usb", "").strip(),
        "file": request.args.get("file", request.args.get("search", "")).strip(),
        "event": request.args.get("event", request.args.get("filter", "all")).strip().lower(),
        "date": date_value,
        "device_code": request.args.get("device_code", "").strip(),
    }


def add_date_filter(sql, params, field, filters):
    if filters["date"]:
        sql += f" AND DATE({field}) = %s"
        params.append(filters["date"])
    elif filters["period"] == "today":
        sql += f" AND DATE({field}) = CURRENT_DATE"
    elif filters["period"] == "7d":
       sql += f" AND {field} >= CURRENT_DATE - INTERVAL '6 days'"
    elif filters["period"] == "month":
        sql += f" AND {field} >= CURRENT_DATE - INTERVAL '29 days'"
    return sql


def fetch_usb_events(filters, limit=None):
    sql = """
        SELECT event_time, event_type, usb_name, drive_letter,
               device_code, username, system_name
        FROM usb_logs
        WHERE 1=1
    """
    params = []

    if filters["usb"]:
        sql += " AND usb_name LIKE %s"
        params.append(f"%{filters['usb']}%")

    event = filters["event"].upper()
    if event not in {"", "ALL", "ALL EVENTS"}:
        if event in {"CONNECTED", "REMOVED"}:
            sql += " AND event_type = %s"
            params.append(event)
        elif event not in {"CREATED", "MODIFIED", "DELETED", "RENAMED"}:
            sql += " AND event_type LIKE %s"
            params.append(f"%{event}%")
        else:
            sql += " AND 1=0"

    if filters.get("device_code"):
        sql += " AND device_code = %s"
        params.append(filters["device_code"])

    sql = add_date_filter(sql, params, "event_time", filters)
    sql += " ORDER BY event_time DESC"
    if limit is not None:
        sql += " LIMIT %s"
        params.append(limit)
    return query(sql, tuple(params))


def fetch_file_events(filters, limit=None):
    sql = """
        SELECT event_time, direction, file_name, file_size_mb, sha256, device_code
        FROM transfer_logs
        WHERE 1=1
    """
    params = []

    if filters["file"]:
        sql += " AND file_name LIKE %s"
        params.append(f"%{filters['file']}%")

    event = filters["event"].upper()
    if event not in {"", "ALL", "ALL EVENTS"}:
        if event == "RENAMED":
            sql += " AND direction LIKE 'RENAMED%'"
        elif event in {"CREATED", "MODIFIED", "DELETED"}:
            sql += " AND direction = %s"
            params.append(event)
        elif event not in {"CONNECTED", "REMOVED"}:
            sql += " AND direction LIKE %s"
            params.append(f"%{event}%")
        else:
            sql += " AND 1=0"

    if filters.get("device_code"):
        sql += " AND device_code = %s"
        params.append(filters["device_code"])

    sql = add_date_filter(sql, params, "event_time", filters)
    sql += " ORDER BY event_time DESC"
    if limit is not None:
        sql += " LIMIT %s"
        params.append(limit)
    return query(sql, tuple(params))


def combined_activity(filters, limit=12):
    usb_rows = fetch_usb_events(filters, limit)
    file_rows = fetch_file_events(filters, limit)
    activity = []

    for row in usb_rows:
        activity.append({
            "event_time": row["event_time"],
            "category": "USB",
            "event": row.get("event_type") or "USB EVENT",
            "title": f"USB {(row.get('event_type') or 'event').title()}",
            "detail": row.get("usb_name") or row.get("device_code") or "Unknown USB",
            "drive": row.get("drive_letter") or "",
        })

    for row in file_rows:
        activity.append({
            "event_time": row["event_time"],
            "category": "FILE",
            "event": row.get("direction") or "FILE EVENT",
            "title": f"File {(row.get('direction') or 'event').title()}",
            "detail": row.get("file_name") or "Unknown file",
            "drive": "",
        })

    activity.sort(key=lambda item: item["event_time"] or datetime.min, reverse=True)
    return fmt_rows(activity[:limit])


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/summary")
def api_summary():
    device_code = request.args.get("device_code", "").strip()

    if device_code:
        total_usb_events = query(
            "SELECT COUNT(*) AS c FROM usb_logs WHERE device_code = %s",
            (device_code,), fetchone=True,
        )["c"]
        total_file_events = query(
            "SELECT COUNT(*) AS c FROM transfer_logs WHERE device_code = %s",
            (device_code,), fetchone=True,
        )["c"]
    else:
        total_usb_events = query("SELECT COUNT(*) AS c FROM usb_logs", fetchone=True)["c"]
        total_file_events = query("SELECT COUNT(*) AS c FROM transfer_logs", fetchone=True)["c"]
    registered_usbs = query(
        "SELECT COUNT(DISTINCT device_code) AS c FROM device_registry", fetchone=True
    )["c"]
    connected = query(
        """
        SELECT COUNT(*) AS c
        FROM device_registry dr
        WHERE (
            SELECT event_type FROM usb_logs
            WHERE device_code = dr.device_code
              AND event_type IN ('CONNECTED', 'REMOVED', 'EXPIRED', 'BLOCKED')
            ORDER BY event_time DESC LIMIT 1
        ) = 'CONNECTED'
        """,
        fetchone=True,
    )["c"]
    return jsonify({
        "total_usb_events": total_usb_events,
        "total_file_events": total_file_events,
        "usb_connected": connected,
        "registered_usbs": registered_usbs,
        "connection_label": "USB Connected" if connected else "No USB Connected",
    })

@app.route("/api/agent/usb-event", methods=["POST"])
def api_agent_usb_event():
    data = request.get_json(silent=True) or {}

    required = [
        "event_time",
        "event_type",
        "usb_name",
        "drive_letter",
        "device_code",
        "username",
        "system_name",
    ]

    missing = [field for field in required if not data.get(field)]
    if missing:
        return jsonify({"error": "Missing fields", "missing": missing}), 400

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO usb_logs
            (event_time, event_type, usb_name, drive_letter,
             device_code, username, system_name)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                data["event_time"],
                data["event_type"],
                data["usb_name"],
                data["drive_letter"],
                data["device_code"],
                data["username"],
                data["system_name"],
            ),
        )

        conn.commit()
        return jsonify({"status": "success"}), 201

    except Exception as error:
        conn.rollback()
        return jsonify({"error": str(error)}), 500

    finally:
        cursor.close()
        conn.close()


@app.route("/api/usb_events")
def api_usb_events():
    return jsonify(fmt_rows(fetch_usb_events(filters_from_request(), safe_limit())))


@app.route("/api/file_events")
def api_file_events():
    return jsonify(fmt_rows(fetch_file_events(filters_from_request(), safe_limit(15))))


@app.route("/api/usb_details")
def api_usb_details():

    rows = query(
        """
        SELECT u.device_code,
               u.username,
               u.system_name,
               u.mac_address,
               u.drive_letter,
               u.usb_name,
               u.event_time AS connected_since

        FROM usb_logs u
        WHERE u.event_type = 'CONNECTED'
          AND u.event_time = (
              SELECT MAX(event_time) FROM usb_logs
              WHERE device_code = u.device_code
                AND event_type IN ('CONNECTED', 'REMOVED', 'EXPIRED', 'BLOCKED')
          )
        ORDER BY u.event_time DESC
        """
    )


    for row in rows:
        drive = row.get("drive_letter")
        filesystem = None
        if read_filesystem and drive:
            try:
                filesystem = read_filesystem(drive)
            except Exception:
                filesystem = None
        row["filesystem"] = filesystem or "Unknown"
        value = row.get("connected_since")
        if hasattr(value, "strftime"):
            row["connected_since"] = value.strftime("%Y-%m-%d %H:%M:%S")
    return jsonify(rows)


@app.route("/api/activity")
def api_activity():
    return jsonify(combined_activity(filters_from_request(), safe_limit(12, 50)))


# ==========================================================
# USB Access Control
# ==========================================================

def admin_name():
    """Admin identity for the action. Falls back to a generic label until
    the dashboard has real authenticated admin accounts."""
    payload = request.get_json(silent=True) or {}
    return (payload.get("admin") or "Admin").strip() or "Admin"


@app.route("/api/access/summary")
def api_access_summary():
    return jsonify({
        "pending": len(pending_requests()),
        "trusted": len(list_trusted_devices()),
        "blocked": len(list_blocked_devices()),
    })


@app.route("/api/access/pending")
def api_access_pending():
    return jsonify(fmt_all_datetimes(pending_requests()))


@app.route("/api/access/trusted")
def api_access_trusted():
    return jsonify(fmt_all_datetimes(list_trusted_devices()))


@app.route("/api/access/blocked")
def api_access_blocked():
    return jsonify(fmt_all_datetimes(list_blocked_devices()))


@app.route("/api/access/approve/<int:request_id>", methods=["POST"])
def api_access_approve(request_id):
    row = get_request_by_id(request_id)
    if not row:
        return jsonify({"error": "Request not found"}), 404

    payload = request.get_json(silent=True) or {}
    duration_minutes = payload.get("duration_minutes")
    if duration_minutes is not None:
        try:
            duration_minutes = int(duration_minutes)
        except (TypeError, ValueError):
            return jsonify({"error": "duration_minutes must be a number"}), 400
        if duration_minutes not in (10, 30, 60):
            return jsonify({"error": "duration_minutes must be 10, 30, or 60"}), 400

    approve_device(
        device_code=row["device_code"],
        serial_number=row["serial_number"],
        device_name=row["device_name"],
        admin=admin_name(),
        request_id=request_id,
        duration_minutes=duration_minutes,
    )

    return jsonify({
        "status": "APPROVED",
        "device_code": row["device_code"],
        "duration_minutes": duration_minutes,
    })


@app.route("/api/access/block/<int:request_id>", methods=["POST"])
def api_access_block(request_id):
    row = get_request_by_id(request_id)
    if not row:
        return jsonify({"error": "Request not found"}), 404

    payload = request.get_json(silent=True) or {}
    reason = (payload.get("reason") or "Unauthorized").strip() or "Unauthorized"

    block_device(
        device_code=row["device_code"],
        serial_number=row["serial_number"],
        admin=admin_name(),
        reason=reason,
        request_id=request_id,
    )

    return jsonify({"status": "BLOCKED", "device_code": row["device_code"]})


@app.route("/api/access/trust/remove", methods=["POST"])
def api_access_remove_trust():
    payload = request.get_json(silent=True) or {}
    device_code = (payload.get("device_code") or "").strip()
    if not device_code:
        return jsonify({"error": "device_code is required"}), 400

    remove_trust(device_code, admin_name())
    return jsonify({"status": "TRUST_REMOVED", "device_code": device_code})


@app.route("/api/access/unblock", methods=["POST"])
def api_access_unblock():
    payload = request.get_json(silent=True) or {}
    device_code = (payload.get("device_code") or "").strip()
    if not device_code:
        return jsonify({"error": "device_code is required"}), 400

    unblock_device(device_code, admin_name())
    return jsonify({"status": "UNBLOCKED", "device_code": device_code})


@app.route("/api/sha256")
def api_sha256():
    file_name = request.args.get("file_name", "")
    device_code = request.args.get("device_code", "").strip()

    sql = """
        SELECT file_name, sha256, event_time FROM transfer_logs
        WHERE file_name = %s AND sha256 IS NOT NULL
    """
    params = [file_name]
    if device_code:
        sql += " AND device_code = %s"
        params.append(device_code)
    sql += " ORDER BY event_time DESC LIMIT 1"

    row = query(sql, tuple(params), fetchone=True)
    return jsonify(fmt_rows([row])[0] if row else {"file_name": file_name, "sha256": None})


def stats_window(period):
    if period == "today":
        labels = [f"{hour:02d}:00" for hour in range(24)]
        return labels, "EXTRACT(HOUR FROM event_time)", "DATE(event_time) = CURRENT_DATE", "hour"

    days = 30 if period in {"month", "all"} else 7

    latest_date = query(
        """
        SELECT GREATEST(
            COALESCE((SELECT MAX(DATE(event_time)) FROM usb_logs), '1970-01-01'),
            COALESCE((SELECT MAX(DATE(event_time)) FROM transfer_logs), '1970-01-01')
        ) AS latest_date
        """,
        fetchone=True,
    )["latest_date"]
    if isinstance(latest_date, str):
        latest_date = datetime.strptime(latest_date, "%Y-%m-%d").date()

    labels = [
        (latest_date - timedelta(days=offset)).isoformat()
        for offset in range(days - 1, -1, -1)
    ]

    latest_date_str = latest_date.isoformat()

    return (
        labels,
        "DATE_FORMAT(event_time, '%Y-%m-%d')",
        f"DATE(event_time) BETWEEN DATE_SUB('{latest_date_str}', INTERVAL {days - 1} DAY) AND '{latest_date_str}'",
        "date",
    )


@app.route("/api/stats/overview")
def api_stats_overview():
    filters = filters_from_request()
    device_code = filters.get("device_code", "")
    period = "today" if filters["date"] else filters["period"]
    labels, group_expr, where_expr, kind = stats_window(period)

    device_clause = " AND device_code = %s" if device_code else ""
    device_params = (device_code,) if device_code else ()

    usb_today = query(
        "SELECT COUNT(*) AS c FROM usb_logs WHERE DATE(event_time) = CURRENT_DATE" + device_clause,
        device_params,
        fetchone=True,
    )["c"]
    file_today = query(
        "SELECT COUNT(*) AS c FROM transfer_logs WHERE DATE(event_time) = CURRENT_DATE" + device_clause,
        device_params,
        fetchone=True,
    )["c"]

    if filters["date"]:
        where_expr = "DATE(event_time) = %s"
        date_params = (filters["date"],)
        labels = [f"{hour:02d}:00" for hour in range(24)]
        group_expr = "HOUR(event_time)"
        kind = "hour"
    else:
        date_params = ()

    if device_code:
        where_expr += " AND device_code = %s"
        date_params = date_params + (device_code,)

    usb_points = query(
        f"SELECT {group_expr} AS bucket, COUNT(*) AS total FROM usb_logs WHERE {where_expr} GROUP BY bucket",
        date_params,
    )
    file_points = query(
        f"SELECT {group_expr} AS bucket, COUNT(*) AS total FROM transfer_logs WHERE {where_expr} GROUP BY bucket",
        date_params,
    )

    def make_series(points):
        values = {}

        for point in points:
            bucket = point["bucket"]

            if kind == "hour":
                key = str(bucket)
            else:
                key = bucket.strftime("%Y-%m-%d") if hasattr(bucket, "strftime") else str(bucket)

            values[key] = point["total"]

        if kind == "hour":
            return [values.get(str(hour), 0) for hour in range(24)]

        return [values.get(label, 0) for label in labels]

    distribution_sql = """
        SELECT CASE
            WHEN direction = 'CREATED' THEN 'Created'
            WHEN direction = 'MODIFIED' THEN 'Modified'
            WHEN direction = 'DELETED' THEN 'Deleted'
            WHEN direction LIKE 'RENAMED%' THEN 'Renamed'
            ELSE direction END AS action,
            COUNT(*) AS total
        FROM transfer_logs WHERE
    """ + where_expr + " GROUP BY action"
    distribution = query(distribution_sql, date_params)

    return jsonify({
        "today": {"usb": usb_today, "file": file_today},
        "labels": labels,
        "usb_series": make_series(usb_points),
        "file_series": make_series(file_points),
        "distribution": distribution,
        "granularity": kind,
        "debug_usb_points": usb_points,
        "debug_file_points": file_points,
    })


@app.route("/api/stats/file_events")
def api_stats_file_events():
    return jsonify(query("""
        SELECT CASE
            WHEN direction = 'CREATED' THEN 'Created'
            WHEN direction = 'MODIFIED' THEN 'Modified'
            WHEN direction = 'DELETED' THEN 'Deleted'
            WHEN direction LIKE 'RENAMED%' THEN 'Renamed'
            ELSE direction END AS action,
            COUNT(*) AS total
        FROM transfer_logs GROUP BY action
    """))


@app.route("/api/stats/usb_events")
def api_stats_usb_events():
    return jsonify(query("""
        SELECT event_type, COUNT(*) AS total FROM usb_logs
        WHERE event_type IN ('CONNECTED', 'REMOVED') GROUP BY event_type
    """))


def report_rows():
    filters = filters_from_request()
    rows = []
    for item in fetch_usb_events(filters):
        rows.append({
            "Time": item.get("event_time"), "Category": "USB", "Event": item.get("event_type"),
            "Name": item.get("usb_name"), "Device Code": item.get("device_code"),
            "Drive": item.get("drive_letter"), "Size (MB)": "",
        })
    for item in fetch_file_events(filters):
        rows.append({
            "Time": item.get("event_time"), "Category": "File", "Event": item.get("direction"),
            "Name": item.get("file_name"), "Device Code": item.get("device_code"),
            "Drive": "", "Size (MB)": item.get("file_size_mb"),
        })
    rows.sort(key=lambda item: item["Time"] or datetime.min, reverse=True)
    for item in rows:
        if hasattr(item["Time"], "strftime"):
            item["Time"] = item["Time"].strftime("%Y-%m-%d %H:%M:%S")
    return rows


def csv_response(rows):
    output = io.StringIO(newline="")
    fields = ["Time", "Category", "Event", "Name", "Device Code", "Drive", "Size (MB)"]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def xlsx_response(rows):
    headers = ["Time", "Category", "Event", "Name", "Device Code", "Drive", "Size (MB)"]

    def column_name(number):
        result = ""
        while number:
            number, remainder = divmod(number - 1, 26)
            result = chr(65 + remainder) + result
        return result

    xml_rows = []
    for row_number, values in enumerate([headers] + [[row.get(h, "") for h in headers] for row in rows], 1):
        cells = []
        for column, value in enumerate(values, 1):
            reference = f"{column_name(column)}{row_number}"
            style = ' s="1"' if row_number == 1 else ""
            cells.append(f'<c r="{reference}" t="inlineStr"{style}><is><t>{xml_escape(str(value or ""))}</t></is></c>')
        xml_rows.append(f'<row r="{row_number}">{"".join(cells)}</row>')

    sheet = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{"".join(xml_rows)}</sheetData></worksheet>'''
    workbook = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Ministry of Defence Report" sheetId="1" r:id="rId1"/></sheets></workbook>'''
    styles = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF0752C9"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFill="1" applyFont="1"/></cellXfs></styleSheet>'''

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>''')
        archive.writestr("_rels/.rels", '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>''')
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>''')
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
        archive.writestr("xl/styles.xml", styles)
    return output.getvalue()


def pdf_response(rows):
    headers = "TIME                CATEGORY EVENT       NAME"
    lines = ["Ministry of Defence EVENT REPORT", datetime.now().strftime("Generated %Y-%m-%d %H:%M:%S"), "", headers, "-" * 92]
    for row in rows:
        name = str(row.get("Name") or "").replace("\\", "/")
        lines.append(f"{str(row.get('Time') or '')[:19]:19} {str(row.get('Category') or '')[:8]:8} {str(row.get('Event') or '')[:11]:11} {name[:47]}")
    if len(lines) == 5:
        lines.append("No events matched the selected filters.")

    pages = [lines[index:index + 48] for index in range(0, len(lines), 48)]
    objects = []
    page_ids = []
    font_id = 3
    next_id = 4
    for page_lines in pages:
        page_id, content_id = next_id, next_id + 1
        next_id += 2
        page_ids.append(page_id)
        commands = ["BT", "/F1 9 Tf", "40 780 Td", "12 TL"]
        for line in page_lines:
            safe = str(line).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            commands.append(f"({safe}) Tj")
            commands.append("T*")
        commands.append("ET")
        stream = "\n".join(commands).encode("latin-1", "replace")
        objects.append((page_id, f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>".encode()))
        objects.append((content_id, f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"))

    base_objects = [
        (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
        (2, f"<< /Type /Pages /Kids [{' '.join(f'{page_id} 0 R' for page_id in page_ids)}] /Count {len(page_ids)} >>".encode()),
        (3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>"),
    ]
    all_objects = sorted(base_objects + objects)
    output = io.BytesIO()
    output.write(b"%PDF-1.4\n")
    offsets = {0: 0}
    for object_id, content in all_objects:
        offsets[object_id] = output.tell()
        output.write(f"{object_id} 0 obj\n".encode() + content + b"\nendobj\n")
    xref = output.tell()
    size = max(offsets) + 1
    output.write(f"xref\n0 {size}\n".encode())
    output.write(b"0000000000 65535 f \n")
    for object_id in range(1, size):
        output.write(f"{offsets[object_id]:010d} 00000 n \n".encode())
    output.write(f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    return output.getvalue()


@app.route("/api/export/<report_format>")
def api_export(report_format):
    rows = report_rows()
    if report_format == "csv":
        return Response(csv_response(rows), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=usb_sentinel_report.csv"})
    if report_format == "xlsx":
        return Response(xlsx_response(rows), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=usb_sentinel_report.xlsx"})
    if report_format == "pdf":
        return Response(pdf_response(rows), mimetype="application/pdf", headers={"Content-Disposition": "attachment; filename=usb_sentinel_report.pdf"})
    return jsonify({"error": "Unsupported report format"}), 404


if __name__ == "__main__":
    app.run(debug=True, port=5000)
