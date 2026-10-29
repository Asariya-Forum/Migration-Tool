"""AsariyaForum PDF inspection, metadata extraction and branding pipeline."""

import os
import re
import time
from pathlib import Path
from io import BytesIO

import fitz
import pytesseract
from PIL import Image, ImageDraw, ImageFont

from app.core.config import settings


BRAND = "www.AsariyaForum.com"

DISCLAIMER = """DISCLAIMER

This book is provided for educational and informational purposes only.
The content is based on available sources and may not represent the
complete subject matter.

The publisher and website (www.asariyaforum.com) do not accept
responsibility for any errors, omissions, or inaccuracies in the content.
Readers are advised to verify information through reliable sources
before acting upon it.

The views and opinions expressed in this book are solely those of the
author and do not necessarily reflect the views of the publisher or
the website.

May Allah accept our efforts.

ASARIYA FORUM
KNOWLEDGE - FAITH - SERVICE"""

SHORT_DISCLAIMER = (
    "Educational use only. Verify accuracy; views belong to the author."
)

LEGACY_BRANDS = (
    "www.kitaaabosunnat.com",
    "www.kitaabosunnat.com",
    "www.kitabosunnat.com",
    "www.kitabo-sunnat.com",
    "www.kitab-o-sunnat.com",
    "www.kitabo sunnat.com",
    "kitaaabosunnat.com",
    "kitaabosunnat.com",
    "kitabosunnat.com",
    "kitabo-sunnat.com",
    "kitab-o-sunnat.com",
)

UUID_PATTERN = (
    r"^[0-9a-fA-F]{8}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{12}$"
)

WATERMARK_FONT = "helv"
WATERMARK_SIZE = 26
WATERMARK_COLOR = (0.58, 0.58, 0.58)

# First-page cover replacement settings.
# Adjust these if the old website appears in a different position.
COVER_BRANDING_BAND_HEIGHT = 48
COVER_BRANDING_FONT_SIZE = 12
COVER_BRANDING_BACKGROUND = (0.93, 0.87, 0.78)
COVER_BRANDING_TEXT_COLOR = (0.20, 0.12, 0.08)


class WatermarkTimeout(TimeoutError):
    """Raised when PDF processing exceeds its configured deadline."""


def clean_metadata_value(value: str) -> str:
    """Normalize metadata and reject legacy branding and UUIDs."""
    value = re.sub(r"\s+", " ", value or "")
    value = value.strip(" \t\r\n:：-–—|")

    if any(brand in value.casefold() for brand in LEGACY_BRANDS):
        return ""

    if re.fullmatch(UUID_PATTERN, value):
        return ""

    return value[:300]


def _tessdata_path() -> Path:
    """Resolve the configured Tesseract language-data directory."""
    path = Path(settings.tessdata_dir)

    if not path.is_absolute():
        path = Path.cwd() / path

    return path.resolve()


def run_ocr(
    image: Image.Image,
    languages: str = "eng+urd",
) -> str:
    """Run OCR using the configured Tesseract installation."""
    executable = Path(settings.tesseract_exe)
    data_dir = _tessdata_path()

    available = [
        lang
        for lang in languages.split("+")
        if (data_dir / f"{lang}.traineddata").is_file()
    ]

    if not executable.is_file() or not available:
        return ""

    old_command = pytesseract.pytesseract.tesseract_cmd
    old_prefix = os.environ.get("TESSDATA_PREFIX")

    try:
        pytesseract.pytesseract.tesseract_cmd = str(executable)
        os.environ["TESSDATA_PREFIX"] = str(data_dir)

        image = image.convert("L")
        image.thumbnail((2200, 3000), Image.Resampling.LANCZOS)

        return pytesseract.image_to_string(
            image,
            lang="+".join(available),
            config="--psm 3",
        )

    except Exception:
        return ""

    finally:
        pytesseract.pytesseract.tesseract_cmd = old_command

        if old_prefix is None:
            os.environ.pop("TESSDATA_PREFIX", None)
        else:
            os.environ["TESSDATA_PREFIX"] = old_prefix


def _extract_pdf_text(
    path: Path,
    max_pages: int = 15,
) -> tuple[str, bool]:
    """Extract selectable text and OCR scanned pages for inspection."""
    chunks = []
    used_ocr = False

    try:
        with fitz.open(path) as document:
            for index in range(min(len(document), max_pages)):
                page = document[index]
                text = page.get_text("text") or ""

                if len(re.sub(r"\s+", "", text)) < 35:
                    pixmap = page.get_pixmap(
                        matrix=fitz.Matrix(1.5, 1.5),
                        alpha=False,
                    )

                    with Image.open(
                        BytesIO(pixmap.tobytes("png"))
                    ) as image:
                        ocr_text = run_ocr(image)

                    if ocr_text.strip():
                        text = (text + "\n" + ocr_text).strip()
                        used_ocr = True

                if text.strip():
                    chunks.append(text)

    except Exception:
        pass

    return "\n\n".join(chunks), used_ocr


def _find_label_value(text: str, kind: str) -> str:
    """Find metadata following common English or Urdu labels."""
    labels = {
        "title": [
            r"book\s*title",
            r"name\s+of\s+(?:the\s+)?book",
            r"title",
            "\u0639\u0646\u0648\u0627\u0646",
            "\u0646\u0627\u0645 \u06a9\u062a\u0627\u0628",
        ],
        "author": [
            r"written\s+by",
            r"authored\s+by",
            r"author",
            "\u0645\u0635\u0646\u0641",
            "\u0645\u0624\u0644\u0641",
            "\u0645\u0631\u062a\u0628",
        ],
        "publisher": [
            r"published\s+by",
            r"publisher",
            r"publication",
            "\u0646\u0627\u0634\u0631",
            "\u0627\u0634\u0627\u0639\u062a",
        ],
    }[kind]

    lines = [
        re.sub(r"\s+", " ", line).strip(" \t:：-–—|")
        for line in (text or "").splitlines()
    ]

    for index, line in enumerate(lines):
        for label in labels:
            match = re.search(
                r"^\s*" + label + r"\s*[:：\-–—]?\s*(.*?)\s*$",
                line,
                re.IGNORECASE,
            )

            if not match:
                continue

            value = clean_metadata_value(match.group(1))

            if value:
                return value

            if index + 1 < len(lines):
                next_value = clean_metadata_value(lines[index + 1])
                if next_value:
                    return next_value

    return ""


def _metadata_from_filename(
    original_filename: str,
) -> tuple[str, str]:
    """Infer a possible title and author from the upload filename."""
    stem = Path(original_filename).stem.strip()
    stem = re.sub(r"[_\s]+", " ", stem).strip()

    if re.fullmatch(UUID_PATTERN, stem):
        return "", ""

    match = re.match(
        r"^(.*?)\s*[\(\[]\s*(.*?)\s*[\)\]]\s*$",
        stem,
    )

    if match:
        return (
            clean_metadata_value(match.group(1)),
            clean_metadata_value(match.group(2)),
        )

    return clean_metadata_value(stem), ""


def _detect_category(text: str) -> str:
    """Suggest a category from basic English and Urdu keywords."""
    lower_text = (text or "").casefold()

    if any(word in lower_text for word in (
        "hadith",
        "hadees",
        "\u062d\u062f\u06cc\u062b",
    )):
        return "Hadith"

    if any(word in lower_text for word in (
        "tafsir",
        "tafseer",
        "\u062a\u0641\u0633\u06cc\u0631",
    )):
        return "Tafseer"

    if any(word in lower_text for word in (
        "fiqh",
        "\u0641\u0642\u06c1",
    )):
        return "Fiqh"

    if "seerah" in lower_text or "sirah" in lower_text:
        return "Seerah"

    if "islamic studies" in lower_text:
        return "Islamic Studies"

    return ""


def inspect_pdf(
    path: Path,
    original_filename: str = "",
) -> dict:
    """Inspect a PDF and return metadata and review flags."""
    path = Path(path)

    if not path.is_file() or path.stat().st_size == 0:
        return {
            "status": "failed",
            "stage": "inspection",
            "message": "PDF file is missing or empty.",
            "metadata": {},
        }

    try:
        with fitz.open(path) as document:
            if len(document) == 0:
                raise ValueError("PDF contains no pages.")

            pdf_info = document.metadata or {}
            page_count = len(document)

    except Exception as exc:
        return {
            "status": "failed",
            "stage": "inspection",
            "message": f"Could not open PDF: {exc}",
            "metadata": {},
        }

    text, used_ocr = _extract_pdf_text(path)
    filename = original_filename or path.name

    filename_title, filename_author = _metadata_from_filename(filename)

    embedded_title = clean_metadata_value(pdf_info.get("title", ""))
    embedded_author = clean_metadata_value(pdf_info.get("author", ""))

    extracted_title = _find_label_value(text, "title")
    extracted_author = _find_label_value(text, "author")
    publisher = _find_label_value(text, "publisher")

    title = embedded_title or extracted_title or filename_title
    author = embedded_author or extracted_author or filename_author

    title_from_filename = bool(
        filename_title and not embedded_title and not extracted_title
    )

    category = _detect_category(text)
    reasons = []

    if not title or title_from_filename:
        reasons.append("Confirm title")

    if not author:
        reasons.append("Author not confidently detected")

    if not publisher:
        reasons.append("Publisher not confidently detected")

    if not category:
        reasons.append("Confirm category")

    if used_ocr:
        reasons.append("OCR used; verify extracted metadata")

    metadata = {
        "title": title,
        "author": author,
        "publisher": publisher,
        "category": category,
        "page_count": page_count,
        "ocr_used": used_ocr,
        "review_required": bool(reasons),
        "review_reasons": reasons,
    }

    return {
        "status": "needs_review" if reasons else "uploaded",
        "stage": "metadata_review" if reasons else "uploaded",
        "message": (
            "PDF inspected. Please verify the extracted metadata."
            if reasons
            else "PDF inspected successfully."
        ),
        "metadata": metadata,
    }


def _check_deadline(started: float, timeout: int) -> None:
    """Raise a timeout before starting another expensive operation."""
    elapsed = time.monotonic() - started

    if elapsed >= timeout:
        raise WatermarkTimeout(
            f"Processing exceeded {timeout}-second limit "
            f"after {elapsed:.1f} seconds."
        )


def _replace_first_page_branding(document: fitz.Document) -> bool:
    """
    Add AsariyaForum branding over the first-page cover branding area.

    This is a visual cover-band replacement, not automatic background
    reconstruction. Adjust COVER_BRANDING_BAND_HEIGHT and colors to fit
    your cover design. It does not change the original input PDF.
    """
    if len(document) == 0:
        return False

    page = document[0]
    rect = page.rect

    band_height = min(COVER_BRANDING_BAND_HEIGHT, rect.height * 0.20)
    band = fitz.Rect(
        rect.x0,
        rect.y0,
        rect.x1,
        rect.y0 + band_height,
    )

    # Cover the old branding area with a configurable background.
    page.draw_rect(
        band,
        color=COVER_BRANDING_BACKGROUND,
        fill=COVER_BRANDING_BACKGROUND,
        width=0,
        overlay=True,
    )

    # Center the new website name.
    font_size = COVER_BRANDING_FONT_SIZE
    text_width = fitz.get_text_length(
        BRAND,
        fontname="hebo",
        fontsize=font_size,
    )

    x = rect.x0 + max(4, (rect.width - text_width) / 2)
    y = rect.y0 + min(band_height - 5, (band_height + font_size) / 2)

    page.insert_text(
        fitz.Point(x, y),
        BRAND,
        fontname="hebo",
        fontsize=font_size,
        color=COVER_BRANDING_TEXT_COLOR,
        overlay=True,
    )

    return True


def _replace_second_page_with_disclaimer(
    document: fitz.Document,
) -> None:
    """
    Replace page two with the disclaimer.

    Use only when the source's second page is known to be an old
    disclaimer page. Otherwise, replacing it may remove book content.
    """
    if len(document) < 2:
        document.new_page(width=595, height=842)

    document.delete_page(1)
    page = document.new_page(pno=1, width=595, height=842)

    page.insert_textbox(
        fitz.Rect(55, 55, 540, 780),
        DISCLAIMER,
        fontsize=11,
        fontname="helv",
        lineheight=1.4,
    )

    page.insert_text(
        fitz.Point(55, 815),
        BRAND,
        fontsize=10,
        fontname="helv",
    )


def _remove_legacy_text(page: fitz.Page) -> bool:
    """
    Redact known legacy domains and selectable text in page margins.

    Text embedded in scanned images cannot reliably be removed here.
    """
    found = False
    page_rect = page.rect
    top_limit = page_rect.y0 + 35
    bottom_limit = page_rect.y1 - 35

    searchable_text = page.get_text("text").casefold()

    for legacy in LEGACY_BRANDS:
        if legacy not in searchable_text:
            continue

        for rect in page.search_for(legacy):
            page.add_redact_annot(rect, fill=(1, 1, 1))
            found = True

    data = page.get_text("dict")

    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue

        for line in block.get("lines", []):
            for span in line.get("spans", []):
                span_text = span.get("text", "").strip()

                if not span_text:
                    continue

                if "asariyaforum.com" in span_text.casefold():
                    continue

                x0, y0, x1, y1 = span.get(
                    "bbox",
                    (0, 0, 0, 0),
                )

                if not (y1 <= top_limit or y0 >= bottom_limit):
                    continue

                rect = fitz.Rect(x0, y0, x1, y1)

                if rect.is_valid and not rect.is_empty:
                    page.add_redact_annot(rect, fill=(1, 1, 1))
                    found = True

    if found:
        page.apply_redactions()

    return found


def _add_branding(
    page: fitz.Page,
    number: int,
) -> None:
    """Add visible foreground watermark, header, footer and disclaimer."""
    rect = page.rect

    header_size = 10
    header_width = fitz.get_text_length(
        BRAND,
        fontname="helv",
        fontsize=header_size,
    )

    page.insert_text(
        fitz.Point(
            rect.x0 + (rect.width - header_width) / 2,
            rect.y0 + 20,
        ),
        BRAND,
        fontsize=header_size,
        fontname="helv",
        color=(0.1, 0.1, 0.1),
        overlay=True,
    )

    watermark_size = WATERMARK_SIZE
    watermark_width = fitz.get_text_length(
        BRAND,
        fontname=WATERMARK_FONT,
        fontsize=watermark_size,
    )

    watermark_x = rect.x0 + (rect.width - watermark_width) / 2
    watermark_y = rect.y0 + (rect.height / 2)

    page.insert_text(
        fitz.Point(watermark_x, watermark_y),
        BRAND,
        fontsize=watermark_size,
        fontname=WATERMARK_FONT,
        color=WATERMARK_COLOR,
        overlay=True,
    )

    page.insert_textbox(
        fitz.Rect(
            rect.x0 + 30,
            rect.y1 - 38,
            rect.x1 - 30,
            rect.y1 - 25,
        ),
        SHORT_DISCLAIMER,
        fontsize=5,
        fontname="helv",
        color=(0.25, 0.25, 0.25),
        align=fitz.TEXT_ALIGN_CENTER,
        overlay=True,
    )

    page.insert_text(
        fitz.Point(rect.x0 + 30, rect.y1 - 10),
        str(number),
        fontsize=8,
        fontname="helv",
        color=(0.2, 0.2, 0.2),
        overlay=True,
    )

    footer_size = 8
    footer_width = fitz.get_text_length(
        BRAND,
        fontname="helv",
        fontsize=footer_size,
    )

    page.insert_text(
        fitz.Point(
            rect.x1 - footer_width - 30,
            rect.y1 - 10,
        ),
        BRAND,
        fontsize=footer_size,
        fontname="helv",
        color=(0.2, 0.2, 0.2),
        overlay=True,
    )


def process_pdf(
    input_path: Path,
    output_path: Path,
) -> dict:
    """Create a branded PDF copy without modifying the original."""
    input_path = Path(input_path)
    output_path = Path(output_path)

    started = time.monotonic()
    timeout = max(1, int(settings.watermark_timeout_seconds))

    if not input_path.is_file():
        return {
            "status": "failed",
            "stage": "processing",
            "message": "Input PDF not found.",
        }

    output_path.parent.mkdir(parents=True, exist_ok=True)

    temporary_path = output_path.with_name(
        output_path.stem + ".tmp.pdf"
    )
    temporary_path.unlink(missing_ok=True)

    pages_processed = 0
    legacy_text_redacted = False
    first_page_branding_replaced = False

    try:
        _check_deadline(started, timeout)

        with fitz.open(input_path) as document:
            if len(document) == 0:
                raise ValueError("PDF contains no pages.")

            original_pages = len(document)

            # Replace the old cover branding on page one.
            first_page_branding_replaced = (
                _replace_first_page_branding(document)
            )

            # Assumes page two is the old disclaimer page.
            _replace_second_page_with_disclaimer(document)

            total_pages = len(document)

            for index in range(total_pages):
                _check_deadline(started, timeout)

                page = document[index]

                legacy_text_redacted = (
                    _remove_legacy_text(page)
                    or legacy_text_redacted
                )

                _add_branding(page, index + 1)
                pages_processed += 1

            _check_deadline(started, timeout)

            existing_metadata = document.metadata or {}

            document.set_metadata({
                "title": existing_metadata.get("title") or "",
                "author": existing_metadata.get("author") or "",
                "subject": "AsariyaForum branded copy",
                "keywords": "AsariyaForum.com",
                "creator": "AsariyaForum PDF Bulk Migration Utility",
                "producer": "AsariyaForum PDF Bulk Migration Utility",
            })

            _check_deadline(started, timeout)

            document.save(
                temporary_path,
                garbage=1,
                deflate=True,
            )

        elapsed = time.monotonic() - started

        if elapsed >= timeout:
            raise WatermarkTimeout(
                f"Processing exceeded {timeout}-second limit "
                f"after PDF save ({elapsed:.1f} seconds)."
            )

        with fitz.open(temporary_path) as result_document:
            output_pages = len(result_document)

            if output_pages != pages_processed:
                raise ValueError(
                    f"Page verification failed: expected "
                    f"{pages_processed}, found {output_pages}."
                )

            missing_watermark_pages = []

            for index in range(output_pages):
                _check_deadline(started, timeout)

                page_text = result_document[index].get_text("text")

                if BRAND.casefold() not in page_text.casefold():
                    missing_watermark_pages.append(index + 1)

        if missing_watermark_pages:
            raise ValueError(
                "Brand text verification failed on page(s): "
                + ", ".join(map(str, missing_watermark_pages[:30]))
            )

        _check_deadline(started, timeout)

        temporary_path.replace(output_path)

        return {
            "status": "completed",
            "stage": "stored",
            "message": (
                "Branded PDF created. Brand text was verified on "
                "every page; visually inspect the cover and sample pages."
            ),
            "output_path": str(output_path.resolve()),
            "original_page_count": original_pages,
            "output_page_count": output_pages,
            "pages_processed": pages_processed,
            "watermark_verified_pages": output_pages,
            "first_page_branding_replaced": first_page_branding_replaced,
            "second_page_replaced": True,
            "legacy_text_redaction_attempted": legacy_text_redacted,
            "scanned_branding_review_required": True,
            "elapsed_seconds": round(time.monotonic() - started, 2),
        }

    except WatermarkTimeout as exc:
        temporary_path.unlink(missing_ok=True)

        return {
            "status": "timed_out",
            "stage": "watermarking",
            "message": str(exc),
            "pages_processed": pages_processed,
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "configured_timeout_seconds": timeout,
        }

    except Exception as exc:
        temporary_path.unlink(missing_ok=True)

        return {
            "status": "failed",
            "stage": "processing",
            "message": f"PDF processing failed: {exc}",
            "pages_processed": pages_processed,
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "configured_timeout_seconds": timeout,
        }