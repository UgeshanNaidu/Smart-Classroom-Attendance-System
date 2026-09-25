"""Real CSV and PDF exports of permission-filtered records."""

import csv
import io
from pathlib import Path
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from datetime import datetime, timezone
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer


def export(rows, fmt):
    headers = [
        "Course",
        "Session",
        "Type",
        "Date (UTC)",
        "Student ID",
        "Student",
        "Status",
        "Source",
        "Reason",
    ]
    values = [
        [
            r["course"],
            r["title"],
            r["kind"],
            datetime.fromtimestamp(r["starts"], timezone.utc).strftime(
                "%Y-%m-%d %H:%M"
            ),
            r["username"],
            r["name"],
            r["status"],
            r["source"] or "",
            r["reason"] or "",
        ]
        for r in rows
    ]
    if fmt == "csv":
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(headers)
        # Prevent spreadsheet formula execution when opening exported user-controlled fields.
        writer.writerows(
            [
                [
                    (
                        "'" + str(v)
                        if str(v).startswith(("=", "+", "-", "@", "\t", "\r"))
                        else v
                    )
                    for v in row
                ]
                for row in values
            ]
        )
        return stream.getvalue().encode("utf-8-sig"), "text/csv", "csv"
    fonts = Path(__file__).resolve().parent / "fonts"
    if "SCAS" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("SCAS", str(fonts / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("SCAS-Bold", str(fonts / "DejaVuSans-Bold.ttf")))
    stream = io.BytesIO()
    styles = getSampleStyleSheet()
    styles["Title"].fontName = "SCAS-Bold"
    styles["BodyText"].fontName = "SCAS"
    style = styles["BodyText"]
    style.fontSize = 8
    style.leading = 10
    data = [
        [Paragraph(escape(str(v)), style) for v in row] for row in [headers] + values
    ]
    table = Table(data, colWidths=[57, 112, 43, 78, 60, 83, 58, 45, 210], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbeafe")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#dbe3ed")),
            ]
        )
    )
    doc = SimpleDocTemplate(
        stream, pagesize=landscape(A4), rightMargin=24, leftMargin=24
    )
    doc.build(
        [
            Paragraph("Smart Classroom Attendance Report", styles["Title"]),
            Paragraph(
                "Generated "
                + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                + " | "
                + str(len(rows))
                + " records",
                style,
            ),
            Spacer(1, 16),
            table,
        ]
    )
    return stream.getvalue(), "application/pdf", "pdf"
