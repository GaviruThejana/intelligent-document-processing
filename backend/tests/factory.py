"""Synthetic document factory: text-layer PDFs, raster images and scanned (image-only) PDFs. No real data."""
import io
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

FONT_PATHS = ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "/usr/share/fonts/dejavu/DejaVuSansMono.ttf"]


def render_pdf(lines: list[str]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Courier", 10)
    y = 800
    for ln in lines:
        c.drawString(50, y, ln)
        y -= 14
        if y < 50:
            c.showPage(); c.setFont("Courier", 10); y = 800
    c.save()
    return buf.getvalue()


def _font(size):
    for p in FONT_PATHS:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def render_image(lines: list[str], fmt="PNG", size=26, degrade=False) -> bytes:
    font = _font(size)
    h = int(size * 1.5) * (len(lines) + 3)
    img = Image.new("RGB", (1500, h), "white")
    d = ImageDraw.Draw(img)
    y = size
    for ln in lines:
        d.text((40, y), ln, fill="black", font=font)
        y += int(size * 1.5)
    if degrade:  # simulate a bad scan: low resolution, blur, skew, noise
        rnd = random.Random(7)
        w, blur, rot, nd = (900, 0.8, 1.0, 40) if degrade == "moderate" else (520, 1.3, 2.5, 12)
        img = img.resize((w, int(h * w / 1500))).filter(ImageFilter.GaussianBlur(blur))
        img = img.rotate(rot, expand=True, fillcolor="white")
        px = img.load()
        for _ in range(img.width * img.height // nd):
            x, yy = rnd.randrange(img.width), rnd.randrange(img.height)
            v = rnd.randrange(60, 200)
            px[x, yy] = (v, v, v)
    buf = io.BytesIO()
    img.save(buf, fmt, **({"quality": 85} if fmt == "JPEG" else {}))
    return buf.getvalue()


def render_scanned_pdf(lines: list[str]) -> bytes:
    img = Image.open(io.BytesIO(render_image(lines)))
    buf = io.BytesIO()
    img.save(buf, "PDF", resolution=150)
    return buf.getvalue()


def invoice_lines(number="INV-1001", date="2026-01-15", supplier="Acme Supplies Ltd", customer="Beta Traders (Pvt) Ltd",
                  currency="USD", items=None, subtotal="101.00", discount="10.00", tax="9.10", total="100.10",
                  title="TAX INVOICE", num_label="Invoice No", date_label="Invoice Date") -> list[str]:
    items = items if items is not None else [("USB-C Cable", "10", "5.00", "50.00"), ("Laptop Stand", "2", "25.50", "51.00")]
    L = [supplier.upper(), title]
    if number is not None:
        L.append(f"{num_label}: {number}")
    if date is not None:
        L.append(f"{date_label}: {date}")
    L += [f"From: {supplier}", f"Bill To: {customer}", f"Currency: {currency}", "",
          "Description            Qty   Unit Price   Amount"]
    for d, qy, u, a in items:
        L.append(f"{d:<22} {qy:<5} {u:<12} {a}")
    L.append("")
    if subtotal is not None: L.append(f"Subtotal: {subtotal}")
    if discount is not None: L.append(f"Discount: {discount}")
    if tax is not None: L.append(f"Tax (10%): {tax}")
    L.append(f"Total: {total}")
    return L


def po_lines():
    L = invoice_lines(number="PO-7788", title="PURCHASE ORDER", num_label="PO Number", date_label="Order Date",
                      subtotal="101.00", discount="0.00", tax="0.00", total="101.00")
    return [l.replace("Bill To:", "Buyer:") for l in L]


def receipt_lines():
    return ["CITY MART", "RECEIPT", "Date: 2026-02-03", "Cashier: 04", "Milk 1L        2   1.50   3.00",
            "Bread          1   2.00   2.00", "Total: 5.00", "Cash tendered: 10.00", "Change due: 5.00",
            "Thank you for your purchase"]


def letter_lines():
    return ["Dear Sir,", "", "We are writing to confirm our meeting next Tuesday at 10am.", "Kind regards,", "J. Perera"]
