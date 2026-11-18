"""Read supported files without executing formulas or retaining lecturer names."""
import csv
from datetime import datetime, time, timedelta
import hashlib
import hmac
from io import BytesIO, StringIO
import json
import re
from zipfile import ZipFile

from .schedule_secret import schedule_secret
from .bookings import CAMPUS

COLUMNS = ("start", "end", "building", "room", "subject", "groups", "teachers", "lesson_type")
MAX_ROWS = 100_000


def teacher_id(value):
    return hmac.new(schedule_secret().encode(), ("teacher:" + " ".join(value.casefold().split())).encode(),
                    hashlib.sha256).hexdigest()[:24]


def identities(raw):
    return sorted({teacher_id(part.strip()) for part in raw.split(";") if part.strip()})


def table_records(headers, data):
    names = [str(cell or "").strip()[:160] for cell in headers]
    if any(not name for name in names) or len(set(names)) != len(names) or len(names) > 80:
        raise ValueError("Заголовки должны быть уникальными и непустыми, максимум 80 колонок")
    for index, cells in enumerate(data):
        if index >= MAX_ROWS:
            raise ValueError("Превышено допустимое количество строк")
        if any(cell is not None and cell != "" for cell in cells):
            if len(cells) > len(names):
                raise ValueError("Значений в строке больше, чем заголовков")
            yield {key: ("" if value is None else str(value))[:4000] for key, value in zip(names, cells)}


def parse_table(data, extension):
    if extension == ".csv":
        try:
            value = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            value = data.decode("cp1251")
        try:
            dialect = csv.Sniffer().sniff(value[:8192], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        lines = csv.reader(StringIO(value), dialect)
        return list(table_records(next(lines, []), lines))
    from openpyxl import load_workbook

    with ZipFile(BytesIO(data)) as archive:
        if sum(info.file_size for info in archive.infolist()) > 80_000_000:
            raise ValueError("Распакованный XLSX слишком большой")
    workbook = load_workbook(BytesIO(data), read_only=True, data_only=True, keep_links=False)
    try:
        sheet = workbook.worksheets[0]
        if sheet.max_row and sheet.max_row > MAX_ROWS + 1 or sheet.max_column and sheet.max_column > 80:
            raise ValueError("Лист XLSX превышает лимит строк или столбцов")
        rows = sheet.values
        return list(table_records(next(rows, []), rows))
    finally:
        workbook.close()


def split_location(location):
    building, sep, room = location.rpartition(" - ")
    if not sep:
        return "", ""
    match = re.fullmatch(r"(?:корпус\s+|ук[- ]?)?([67])", building.strip(), re.I)
    return (match[1] if match else building.strip()), room.strip()


def parse_ics(data, date_from, date_to, scope):
    from icalendar import Calendar
    import recurring_ical_events

    calendar = Calendar.from_ical(data)
    for event in calendar.walk("VEVENT"):
        rule = event.get("RRULE")
        if rule and str(rule.get("FREQ", [""])[0]).upper() in {"SECONDLY", "MINUTELY", "HOURLY"}:
            raise ValueError("Повторения чаще одного раза в сутки не поддерживаются")
    events = recurring_ical_events.of(calendar).between(
        datetime.combine(date_from, time.min, CAMPUS),
        datetime.combine(date_to + timedelta(days=1), time.min, CAMPUS),
    )
    if len(events) > MAX_ROWS:
        raise ValueError("Слишком много занятий ICS")
    rows = []
    for event in events:
        if str(event.get("STATUS", "")).upper() == "CANCELLED":
            continue
        building, room = split_location(str(event.get("LOCATION", "")))
        rows.append(dict(start=str(event.decoded("DTSTART")), end=str(event.decoded("DTEND")),
                         building=str(event.get("X-BUILDING", building or scope)),
                         room=str(event.get("X-ROOM", room)), subject=str(event.get("SUMMARY", "")),
                         groups=str(event.get("X-GROUPS", "")), teachers=str(event.get("X-TEACHERS", ""))))
    return rows


def parse_snapshot(data, date_from, date_to):
    snapshot = json.loads(data)
    for group in snapshot["groups"]:
        for entry in group["lessons"]:
            subject, *details = entry["details"]
            building, room = split_location(details[-2])
            teacher = details[0] if len(details) == 3 and len(details[0].split()) == 3 else ""
            start, end = entry["time"].split("-")
            for day in entry["dates"]:
                if date_from.isoformat() <= day <= date_to.isoformat():
                    yield dict(start=f"{day}T{start}", end=f"{day}T{end}", building=building,
                               room=room if room.casefold() != "уточняется" else "", subject=subject,
                               groups=group["name"], teachers=teacher)


def parse_datetime(value):
    if "T" not in value and " " not in value:
        raise ValueError("нужны дата и время")
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=CAMPUS)
