"""Render invoices to PDF (plan 10.2: several layouts). The PDFs are real documents for the vision reader.

Layout 6 puts the credit for returned goods in a page-2 footer, as in the plan's missed-credit story.
Free text on the invoice (notes) is printed as it would be, including any hidden instruction.
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from .domain import Invoice

LAYOUTS = {
    0: {"title_x": 20, "accent": colors.HexColor("#1f3a5f"), "cols": ("item", "desc", "qty", "unit", "price", "amount")},
    1: {"title_x": 120, "accent": colors.HexColor("#5f1f1f"), "cols": ("desc", "item", "qty", "price", "amount", "unit")},
    2: {"title_x": 20, "accent": colors.HexColor("#1f5f3a"), "cols": ("item", "qty", "unit", "desc", "price", "amount")},
    3: {"title_x": 70, "accent": colors.HexColor("#3a3a3a"), "cols": ("desc", "qty", "unit", "price", "amount", "item")},
    4: {"title_x": 20, "accent": colors.HexColor("#5f4a1f"), "cols": ("item", "desc", "unit", "qty", "price", "amount")},
    5: {"title_x": 120, "accent": colors.HexColor("#1f4f5f"), "cols": ("item", "desc", "qty", "unit", "price", "amount")},
    6: {"title_x": 20, "accent": colors.HexColor("#4a1f5f"), "cols": ("item", "desc", "qty", "unit", "price", "amount")},
    7: {"title_x": 70, "accent": colors.HexColor("#2f2f5f"), "cols": ("desc", "item", "qty", "unit", "price", "amount")},
}
HEAD = {"item": "Code", "desc": "Description", "qty": "Qty", "unit": "Unit", "price": "Unit price (USD)", "amount": "Amount (USD)"}
X = {0: 15, 1: 40, 2: 95, 3: 115, 4: 135, 5: 168}


def _columns(c: canvas.Canvas, cols: tuple, rows: list[dict]) -> list[float]:
    """Column x positions: the fixed grid X, pushed right where a header or value would overlap the next column."""
    xs, edge = [], 0.0
    for j, col in enumerate(cols):
        x = max(X[j] * mm, edge)
        xs.append(x)
        wide = max([c.stringWidth(HEAD[col], "Helvetica-Bold", 9)] + [c.stringWidth(r[col], "Helvetica", 9) for r in rows])
        edge = x + wide + 3 * mm
    return xs


def render(inv: Invoice, path: Path) -> Path:
    L = LAYOUTS[inv.layout % 8]
    c = canvas.Canvas(str(path), pagesize=A4)
    w, h = A4
    c.setFillColor(L["accent"])
    c.setFont("Helvetica-Bold", 18)
    c.drawString(L["title_x"] * mm, h - 25 * mm, inv.supplier_name)
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 9)
    c.drawString(L["title_x"] * mm, h - 31 * mm, f"Tax ID {inv.tax_id}   accounts@{inv.sender_domain}")
    c.setFont("Helvetica-Bold", 13)
    c.drawString(15 * mm, h - 45 * mm, "INVOICE")
    c.setFont("Helvetica", 10)
    meta = [("Invoice no.", inv.inv_no), ("Your PO", inv.po_id), ("Date", inv.date), ("Due", inv.due_date),
            ("Terms", "2% 10 days, net 30" if inv.terms == "2/10net30" else "Net 30"), ("Currency", inv.currency)]
    for i, (k, v) in enumerate(meta):
        c.drawString(15 * mm, h - (53 + 6 * i) * mm, f"{k}:")
        c.drawString(45 * mm, h - (53 + 6 * i) * mm, str(v))
    y = h - 100 * mm
    rows = [{"item": l.item, "desc": l.desc, "qty": f"{l.qty:g}", "unit": l.unit, "price": f"{l.price:,.2f}",
             "amount": f"{l.amount:,.2f}"} for l in inv.lines]
    xs = _columns(c, L["cols"], rows)
    c.setFont("Helvetica-Bold", 9)
    for j, col in enumerate(L["cols"]):
        c.drawString(xs[j], y, HEAD[col])
    c.line(15 * mm, y - 2 * mm, 195 * mm, y - 2 * mm)
    c.setFont("Helvetica", 9)
    for vals in rows:
        y -= 7 * mm
        for j, col in enumerate(L["cols"]):
            c.drawString(xs[j], y, vals[col])
    y -= 12 * mm
    c.setFont("Helvetica-Bold", 10)
    footer_credit = inv.credit and inv.layout == 6
    if inv.credit and not footer_credit:
        c.drawString(120 * mm, y, f"Less credit {inv.credit_note_ref}: -{inv.credit:,.2f}")
        y -= 6 * mm
    c.drawString(120 * mm, y, f"{'Subtotal' if footer_credit else 'Total due'}: {inv.gross if footer_credit else inv.total:,.2f}")
    y -= 14 * mm
    c.setFont("Helvetica", 9)
    if inv.bank_account:
        c.drawString(15 * mm, y, f"Pay to: {inv.bank_account}")
        y -= 6 * mm
    if inv.notes:
        c.setFillColor(colors.HexColor("#9a9a9a"))
        c.setFont("Helvetica", 6)
        for chunk in [inv.notes[i:i + 140] for i in range(0, len(inv.notes), 140)]:
            c.drawString(15 * mm, y, chunk)
            y -= 3.5 * mm
        c.setFillColor(colors.black)
    if footer_credit:
        c.showPage()
        c.setFont("Helvetica", 8)
        c.drawString(15 * mm, 30 * mm, "Terms and conditions apply. Goods remain our property until paid in full.")
        c.drawString(15 * mm, 24 * mm, f"Less credit for returned goods {inv.credit_note_ref}: -{inv.credit:,.2f}.  "
                                       f"Net amount due: {inv.total:,.2f}")
    c.showPage()
    c.save()
    return path


def photo_from_pdf(pdf: Path, out: Path, seed: int = 3) -> Path:
    """A phone photo of the first page: tilted, perspective, uneven light, sensor noise, soft focus, JPEG.

    Made from the rendered PDF so the photo and the PDF are the same invoice (task 2: the duplicate arrives as a photo).
    """
    import numpy as np
    import pypdfium2 as pdfium
    from PIL import Image, ImageFilter

    rng = np.random.default_rng(seed)
    page = pdfium.PdfDocument(pdf.read_bytes())[0].render(scale=1.6).to_pil().convert("RGB")
    w, h = page.size
    # Lay the page on a desk, a little larger than the page, and photograph it at an angle.
    desk = Image.new("RGB", (int(w * 1.18), int(h * 1.12)), (122, 104, 86))
    desk.paste(page.rotate(-2.3, expand=False, fillcolor=(122, 104, 86)), (int(w * 0.09), int(h * 0.05)))
    W, H = desk.size
    # Perspective: the top edge is further from the camera than the bottom.
    dx, dy = W * 0.045, H * 0.02
    src = [(dx, dy), (W - dx * 0.6, 0), (W, H), (0, H - dy)]
    dst = [(0, 0), (W, 0), (W, H), (0, H)]
    a = []
    for (x, y), (u, v) in zip(dst, src):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y])
    coeffs = np.linalg.solve(np.array(a, float), np.array([c for p in src for c in p], float))
    img = desk.transform((W, H), Image.Transform.PERSPECTIVE, tuple(coeffs), Image.Resampling.BICUBIC)
    arr = np.asarray(img, dtype=np.float32)
    # Warm indoor light falling off toward one corner, plus noise.
    yy, xx = np.mgrid[0:H, 0:W]
    light = 1.05 - 0.28 * ((xx / W) * 0.6 + (yy / H) * 0.4)
    arr = arr * light[..., None] * np.array([1.0, 0.97, 0.9])
    arr += rng.normal(0, 6.0, arr.shape)
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.8))
    img = img.resize((int(W * 0.75), int(H * 0.75)), Image.Resampling.LANCZOS)
    img.save(out, "JPEG", quality=72)
    return out
