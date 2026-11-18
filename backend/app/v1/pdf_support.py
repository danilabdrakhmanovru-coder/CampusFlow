"""Cyrillic font registration shared by PDF exports."""
from os import environ, name
from pathlib import Path
from threading import Lock

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

pdf_lock = Lock()


def document_font():
    font = "CampusFlowDocument"
    if font not in pdfmetrics.getRegisteredFontNames():
        path = (Path(environ.get("WINDIR", "C:/Windows")) / "Fonts/arial.ttf" if name == "nt"
                else Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
        pdfmetrics.registerFont(TTFont(font,str(path)))
    return font
