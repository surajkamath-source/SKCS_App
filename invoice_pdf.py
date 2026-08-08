"""
invoice_pdf.py
---------------
Generates the invoice PDF. Kept separate from app.py so the firm's
letterhead/branding can be edited in one place.
"""

import os
from io import BytesIO

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image,
)

FIRM_NAME = "S K Consultancy Services"
FIRM_TAGLINE = "One roof for accounts, taxation and allied services"
FIRM_ADDRESS = "Double Tank Road, Keralapura - 573 136. Hassan District"
FIRM_CONTACT = "Email: consultants.skcs@gmail.com | Mobile: +91 81978 39824"
FIRM_GST_REGISTERED = False  # flip to True once GST-registered; feeds the declaration line and GST column
LOGO_PATH = "JAI_SHREE_RAM_LOGO4.png"


def generate_invoice_pdf(client_name, invoice_no, invoice_date, line_items, remarks="",
                          gst_applicable=False, gst_amount=0.0):
    """
    line_items: list of dicts like {"description": str, "amount": float}
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, rightMargin=20, leftMargin=20, topMargin=20, bottomMargin=20)
    styles = getSampleStyleSheet()
    elements = []

    if os.path.exists(LOGO_PATH):
        elements.append(Image(LOGO_PATH, width=80 * mm, height=40 * mm))

    elements.append(Paragraph(f"<b>{FIRM_NAME}</b>", styles["Title"]))
    elements.append(Paragraph(FIRM_TAGLINE, styles["Normal"]))
    elements.append(Paragraph(FIRM_ADDRESS, styles["Normal"]))
    elements.append(Paragraph(FIRM_CONTACT, styles["Normal"]))
    elements.append(Spacer(1, 12))

    elements.append(Paragraph("<b>INVOICE</b>", styles["Heading1"]))
    elements.append(Spacer(1, 10))

    details = [
        ["Invoice No", invoice_no],
        ["Client Name", client_name],
        ["Invoice Date", invoice_date],
    ]
    table = Table(details, colWidths=[120, 300])
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 1, colors.black),
        ("BACKGROUND", (0, 0), (0, -1), colors.lightgrey),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 15))

    subtotal = sum(float(li["amount"]) for li in line_items)

    bill_data = [["Particulars", "Amount (Rs.)"]]
    for li in line_items:
        bill_data.append([li["description"], f"{float(li['amount']):,.2f}"])

    bill_table = Table(bill_data, colWidths=[350, 120])
    bill_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 1, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (1, 1), (1, -1), "RIGHT"),
    ]))
    elements.append(bill_table)
    elements.append(Spacer(1, 10))

    total = subtotal
    total_rows = [["Subtotal", f"Rs. {subtotal:,.2f}"]]
    if gst_applicable and gst_amount:
        total_rows.append(["GST", f"Rs. {float(gst_amount):,.2f}"])
        total = subtotal + float(gst_amount)
    total_rows.append(["TOTAL", f"Rs. {total:,.2f}"])

    total_table = Table(total_rows, colWidths=[350, 120])
    total_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 1, colors.black),
        ("BACKGROUND", (0, -1), (-1, -1), colors.lightgrey),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ]))
    elements.append(total_table)
    elements.append(Spacer(1, 15))

    if remarks:
        elements.append(Paragraph("<b>Remarks:</b>", styles["Heading3"]))
        elements.append(Paragraph(remarks, styles["Normal"]))
        elements.append(Spacer(1, 10))

    if not FIRM_GST_REGISTERED and not gst_applicable:
        elements.append(Paragraph(
            "We are not registered under GST. Hence GST is not applicable on this invoice.",
            styles["Italic"],
        ))

    elements.append(Spacer(1, 30))
    elements.append(Paragraph(f"<b>For {FIRM_NAME}</b>", styles["Normal"]))
    elements.append(Spacer(1, 40))
    elements.append(Paragraph("Authorised Signatory", styles["Normal"]))

    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()
    return pdf
