"""Printable and editable weekly schedule downloads."""
from collections import defaultdict
from datetime import timedelta
from html import escape
from io import BytesIO

from docx import Document
from docx.shared import Cm
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, TableStyle

from .bookings import CAMPUS
from .pdf_support import document_font, pdf_lock

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
HEADERS = ("Время", "Занятие", "Аудитория", "Группы")
WEEKDAYS = ("Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье")


def export_rows(lessons, first, last):
    grouped = defaultdict(list)
    for item in lessons:
        start, end = (item[key].astimezone(CAMPUS) for key in ("start", "end"))
        room = item["room"] or "Аудитория уточняется"
        if item["building"]:
            room += f" — корпус {item['building']}"
        subject = item["subject"]
        teachers = ", ".join(t["label"] for t in item["teachers"])
        if teachers:
            subject += "\n" + teachers
        grouped[start.date()].append((f"{start:%H:%M}–{end:%H:%M}",subject,room,", ".join(item["groups"]) or "—"))
    for offset in range((last-first).days+1):
        day = first+timedelta(days=offset)
        yield f"{WEEKDAYS[day.weekday()]}, {day:%d.%m.%Y}", grouped[day]


def as_pdf(subtitle, days):
    result = BytesIO()
    with pdf_lock:
        font = document_font()
        body = ParagraphStyle("body", fontName=font, fontSize=9, leading=13)
        day_style = ParagraphStyle("day", parent=body, fontSize=12, leading=16, spaceBefore=12,
                                   spaceAfter=5, keepWithNext=True)
        title = ParagraphStyle("title", parent=body, fontSize=19, leading=24, spaceAfter=8)
        header = ParagraphStyle("header", parent=body, textColor=colors.HexColor("#302252"))

        def phrase(value, style=body):
            return Paragraph(escape(value).replace("\n", "<br/>"), style)

        content = [phrase("Расписание занятий",title), phrase(subtitle)]
        for label, rows in days:
            content.append(phrase(label,day_style))
            if not rows:
                content.append(phrase("Занятий нет."))
                continue
            table = LongTable([[phrase(key,header) for key in HEADERS],
                               *[[phrase(value) for value in row] for row in rows]],
                              colWidths=(72,200,135,100), repeatRows=1)
            table.setStyle(TableStyle([
                ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#F2EEFC")),
                ("VALIGN",(0,0),(-1,-1),"TOP"),
                ("LINEBELOW",(0,0),(-1,-1),0.4,colors.HexColor("#DCD5F3")),
                ("TOPPADDING",(0,0),(-1,-1),5),
                ("BOTTOMPADDING",(0,0),(-1,-1),5),
            ]))
            content.append(table)
        SimpleDocTemplate(result,pagesize=A4,leftMargin=44,rightMargin=44,topMargin=39,bottomMargin=39,
                          title="Расписание занятий CampusFlow").build(content)
    return result.getvalue()


def as_docx(subtitle, days):
    document = Document()
    section = document.sections[0]
    section.top_margin = section.bottom_margin = Cm(1.7)
    section.left_margin = section.right_margin = Cm(1.7)
    document.add_paragraph("Расписание занятий",style="Title")
    document.add_paragraph(subtitle)
    for label, rows in days:
        document.add_heading(label,level=1)
        if not rows:
            document.add_paragraph("Занятий нет.")
            continue
        table = document.add_table(rows=1,cols=len(HEADERS))
        table.style = "Light Shading Accent 1"
        table.autofit = False
        for column, width in zip(table.columns, (2.7, 6.9, 4.3, 3.7)):
            column.width = Cm(width)
        for cell, value in zip(table.rows[0].cells, HEADERS):
            cell.text = value
        for row in rows:
            for cell, value in zip(table.add_row().cells,row):
                cell.text = value
        for row in table.rows:
            for cell, column in zip(row.cells,table.columns):
                cell.width = column.width
    result = BytesIO()
    document.save(result)
    return result.getvalue()
