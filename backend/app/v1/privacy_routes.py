"""Downloadable PDF versions of the public privacy documents."""
from html import escape
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Response
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from .auth import db_session
from .privacy import documents
from .pdf_support import document_font, pdf_lock

router = APIRouter(prefix="/privacy", tags=["privacy"])


@router.get("/policy")
def policy(response: Response, db=Depends(db_session)):
    response.headers["Cache-Control"] = "no-store"
    return documents(db)


@router.get("/documents/{kind}.pdf")
def document_pdf(kind: str, db=Depends(db_session)):
    data = documents(db)
    document = data["documents"].get(kind)
    if not document:
        raise HTTPException(404, "Документ не найден")
    dest = BytesIO()
    with pdf_lock:
        font = document_font()
        styles = {
            "title": ParagraphStyle("title", fontName=font, fontSize=18, leading=23, spaceAfter=16),
            "section": ParagraphStyle("section", fontName=font, fontSize=12, leading=16, spaceAfter=5,
                                      keepWithNext=True, textColor=colors.HexColor("#5033AD")),
            "body": ParagraphStyle("body", fontName=font, fontSize=10, leading=15, spaceAfter=8),
        }

        def paragraph(text, style="body"):
            return Paragraph(escape(text), styles[style])

        nodes = [paragraph(document["title"], "title"),
                 paragraph("Шаблон для пилота. Требуется согласование университетом."),
                 paragraph("Редакция " + data["version"])]
        for key, label in (("effective_date", "Дата вступления в силу"), ("operator", "Оператор"),
                           ("responsible", "Ответственный за обработку данных"), ("contact", "Контакт")):
            nodes.append(paragraph(label + " — " + (data["operator"][key] or "не указано")))
        nodes.append(Spacer(1, 10))
        for i, item in enumerate(document["sections"], 1):
            nodes.extend([paragraph(f'{i}. {item["title"]}', "section"), paragraph(item["text"])])
        SimpleDocTemplate(dest, title=document["title"]).build(nodes)
    return Response(dest.getvalue(), media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="campusflow-{kind}.pdf"',
        "Cache-Control": "no-store",
    })
