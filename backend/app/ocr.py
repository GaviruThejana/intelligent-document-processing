"""Text acquisition: PDF text layer first (exact, no OCR error), Tesseract OCR for images / scanned PDFs."""
from dataclasses import dataclass, field
from statistics import mean

from .config import get_settings


class OcrUnavailable(Exception):
    """OCR engine/tooling missing or failing -> document is routed to manual review."""


@dataclass
class OcrLine:
    text: str
    confidence: float | None  # 0-100; None = unavailable (e.g. PDF text layer)


@dataclass
class OcrResult:
    lines: list[OcrLine] = field(default_factory=list)
    method: str = "none"
    warnings: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(l.text for l in self.lines)

    @property
    def mean_confidence(self) -> float | None:
        vals = [l.confidence for l in self.lines if l.confidence is not None]
        return round(mean(vals), 1) if vals else None


def _ocr_image(img) -> list[OcrLine]:
    try:
        import pytesseract
        from PIL import ImageOps
    except ImportError as e:  # pragma: no cover
        raise OcrUnavailable(f"OCR libraries missing: {e}") from e
    img = ImageOps.autocontrast(img.convert("L"))
    if img.width < 1500:  # upscale small scans: Tesseract works best at ~300 dpi
        ratio = 1500 / img.width
        img = img.resize((1500, int(img.height * ratio)))
    try:
        data = pytesseract.image_to_data(img, config="--psm 6", output_type=pytesseract.Output.DICT)
    except pytesseract.TesseractNotFoundError as e:
        raise OcrUnavailable("Tesseract binary not found") from e
    except pytesseract.TesseractError as e:
        raise OcrUnavailable(f"Tesseract failed: {e}") from e
    rows: dict[tuple, list[tuple[str, float]]] = {}
    for i, word in enumerate(data["text"]):
        conf = float(data["conf"][i])
        if word.strip() and conf >= 0:
            key = (data["page_num"][i], data["block_num"][i], data["par_num"][i], data["line_num"][i])
            rows.setdefault(key, []).append((word.strip(), conf))
    return [OcrLine(" ".join(w for w, _ in ws), round(mean(c for _, c in ws), 1)) for ws in rows.values()]


def read_document(path: str, content_type: str) -> OcrResult:
    s = get_settings()
    if content_type == "application/pdf":
        import pdfplumber  # corrupt PDFs raise here -> caller marks document Failed (retryable)

        lines: list[OcrLine] = []
        with pdfplumber.open(path) as pdf:
            page_limit_hit = len(pdf.pages) > s.max_pdf_pages
            pages = pdf.pages[: s.max_pdf_pages]
            for p in pages:
                for ln in (p.extract_text() or "").splitlines():
                    if ln.strip():
                        lines.append(OcrLine(ln.strip(), None))
        if sum(len(l.text) for l in lines) >= 30:
            return OcrResult(lines, "pdf_text", ["PDF_PAGE_LIMIT"] if page_limit_hit else [])
        # Scanned PDF: rasterise and OCR
        try:
            from pdf2image import convert_from_path
            from pdf2image.exceptions import PDFInfoNotInstalledError

            images = convert_from_path(path, dpi=200, last_page=s.max_pdf_pages)
        except PDFInfoNotInstalledError as e:
            raise OcrUnavailable("poppler (pdftoppm) not installed") from e
        out: list[OcrLine] = []
        for im in images:
            out += _ocr_image(im)
        return OcrResult(out, "tesseract", ["PDF_PAGE_LIMIT"] if page_limit_hit else [])
    from PIL import Image

    with Image.open(path) as im:
        im.load()
        return OcrResult(_ocr_image(im), "tesseract")
