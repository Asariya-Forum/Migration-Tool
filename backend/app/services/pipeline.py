
"""Conservative local PDF inspection and processing pipeline."""
import json, os, re, time
from pathlib import Path
from io import BytesIO

import fitz
import pytesseract
from PIL import Image
from pypdf import PdfReader

from app.core.config import settings

DISCLAIMER = """DISCLAIMER

This book is provided for educational and informational purposes only. The content is based on available sources and may not represent the complete subject matter.

The publisher and website (www.asariyaforum.com) do not accept responsibility for any errors, omissions, or inaccuracies in the content. Readers are advised to verify the information through reliable sources before acting upon it.

The views and opinions expressed in this book are solely those of the author and do not necessarily reflect the views of the publisher or the website.

May Allah accept our efforts.

ASARIYA FORUM
KNOWLEDGE • FAITH • SERVICE"""

LEGACY_BRANDS = ("kitabosunnat.com", "www.kitabosunnat.com")
TESSERACT_EXE = Path(settings.tesseract_exe)
TESSDATA_DIR = Path(settings.tessdata_dir)

if not TESSDATA_DIR.is_absolute():
    TESSDATA_DIR = (Path.cwd() / TESSDATA_DIR).resolve()


class WatermarkTimeout(TimeoutError):
    pass


def clean_metadata_value(value: str) -> str:
    value = re.sub(r"\s+", " ", value or "").strip(" \t\r\n:：-–—|")
    if not value or any(b in value.lower() for b in LEGACY_BRANDS):
        return ""
    return value[:300]


def run_ocr(image: Image.Image, languages: str = "eng+urd") -> str:
    """OCR a rendered page when Tesseract and language data are installed."""
    if not TESSERACT_EXE.is_file():
        return ""
    langs = [lang for lang in languages.split("+") if (TESSDATA_DIR / f"{lang}.traineddata").is_file()]
    if not langs:
        return ""
    old_cmd = pytesseract.pytesseract.tesseract_cmd
    old_prefix = os.environ.get("TESSDATA_PREFIX")
    try:
        pytesseract.pytesseract.tesseract_cmd = str(TESSERACT_EXE)
        os.environ["TESSDATA_PREFIX"] = str(TESSDATA_DIR)
        image = image.convert("L")
        image.thumbnail((2200, 3000), Image.Resampling.LANCZOS)
        return pytesseract.image_to_string(image, lang="+".join(langs), config="--psm 3")
    except Exception:
        return ""
    finally:
        pytesseract.pytesseract.tesseract_cmd = old_cmd
        if old_prefix is None:
            os.environ.pop("TESSDATA_PREFIX", None)
        else:
            os.environ["TESSDATA_PREFIX"] = old_prefix


def _extract_pdf_text(path: Path, max_pages: int = 15) -> tuple[str, bool]:
    chunks, used_ocr = [], False
    try:
        with fitz.open(path) as doc:
            for page in list(doc)[:max_pages]:
                text = page.get_text("text") or ""
                if len(re.sub(r"\s+", "", text)) < 35:
                    pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
                    ocr = run_ocr(Image.open(BytesIO(pix.tobytes("png"))))
                    if ocr.strip():
                        text = (text + "\n" + ocr).strip()
                        used_ocr = True
                if text.strip():
                    chunks.append(text)
    except Exception:
        pass
    return "\n\n".join(chunks), used_ocr


def _find_label_value(text: str, kind: str) -> str:
    labels = {
        "title": [r"title", r"book title", r"name of book", r"عنوان", r"کتاب کا نام", r"نام کتاب"],
        "author": [r"author", r"written by", r"authored by", r"مصنف", r"مؤلف", r"تالیف", r"مرتب"],
        "publisher": [r"publisher", r"published by", r"publication", r"ناشر", r"اشاعت", r"مطبوعہ"],
    }[kind]
    lines = [re.sub(r"\s+", " ", x).strip(" \t:：-–—|") for x in (text or "").splitlines()]