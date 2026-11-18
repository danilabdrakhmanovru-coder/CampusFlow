from datetime import date
from io import BytesIO

from openpyxl import Workbook

from app.v1.import_files import parse_ics, parse_table


def test_xlsx_reads_first_sheet():
    workbook = Workbook()
    workbook.active.append(["Начало", "Дисциплина"])
    workbook.active.append(["2026-11-16 11:35", "Математика"])
    data = BytesIO()
    workbook.save(data)
    assert parse_table(data.getvalue(), ".xlsx") == [
        {"Начало": "2026-11-16 11:35", "Дисциплина": "Математика"}
    ]


def test_ics_weekly_recurrence_and_exdate():
    data = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//CampusFlow//Tests//EN\r\n"
        "BEGIN:VEVENT\r\nUID:synthetic-1\r\nDTSTAMP:20261101T000000Z\r\n"
        "DTSTART:20261116T060000Z\r\nDTEND:20261116T070000Z\r\n"
        "RRULE:FREQ=WEEKLY;COUNT=3\r\nEXDATE:20261123T060000Z\r\n"
        "LOCATION:6 - 101\r\nSUMMARY:Example\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    ).encode()
    rows = parse_ics(data, date(2026, 11, 16), date(2026, 12, 1), "6")
    assert [row["start"][:10] for row in rows] == ["2026-11-16", "2026-11-30"]
    assert all(row["room"] == "101" and row["building"] == "6" for row in rows)


def test_schedule_secret_is_required_and_independent(monkeypatch):
    import pytest
    from app.v1.schedule_secret import schedule_secret

    jwt_key = "jwt-test-key-with-at-least-32-bytes"
    monkeypatch.setenv("CAMPUSFLOW_JWT_SECRET", jwt_key)
    monkeypatch.delenv("CAMPUSFLOW_SCHEDULE_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        schedule_secret()
    monkeypatch.setenv("CAMPUSFLOW_SCHEDULE_SECRET", jwt_key)
    with pytest.raises(RuntimeError):
        schedule_secret()
    key = "schedule-test-key-with-at-least-32-bytes"
    monkeypatch.setenv("CAMPUSFLOW_SCHEDULE_SECRET", key)
    assert schedule_secret() == key
