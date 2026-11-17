
from __future__ import annotations

import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import logfire
import pymupdf

from agentic_rag_e2e.observability import install_auto_tracing

from .schemas import ExtractionResult, PageData, normalize_metadata

# ---------------------------------------------------------------------
# PyMuPDF extractor
# ---------------------------------------------------------------------

def extract_with_pymupdf(
    pdf_path: str | Path,
    count_images: bool = False,
) -> ExtractionResult:
    """
    Extract text, metadata, and optional image resource counts
    using PyMuPDF.

    Args:
        pdf_path: Path to the PDF.
        count_images: Whether to count image resources per page.

    Returns:
        Structured extraction result.

    Notes:
        image_count represents the number of image resources
        referenced by each page, not displayed image instances.
    """

    path = Path(pdf_path)
    start = time.perf_counter()

    pages: list[PageData] = []
    total_images = 0

    with pymupdf.open(path) as doc:

        if doc.needs_pass:
            raise RuntimeError(
                f"PDF is password protected: {path}"
            )

        metadata = normalize_metadata(doc.metadata, format="PDF")
        total_pages = len(doc)

        for page_num, page in enumerate(doc, start=1):

            # Extract text.
            text = page.get_text("text", sort=True).strip()

            # Get text blocks.
            blocks = page.get_text("blocks")

            # Count referenced image resources if requested.
            image_count = None

            if count_images:
                image_count = len(page.get_images())
                total_images += image_count

            pages.append({
                "page_num": page_num,
                "text": text,
                "word_count": len(text.split()),
                "block_count": len(blocks),
                "image_count": image_count,
            })

    return {
        "file": str(path),
        "extractor": "pymupdf",
        "total_pages": total_pages,
        "pages": pages,
        "metadata": metadata,
        "image_count": total_images if count_images else None,
        "extraction_time_s": round(
            time.perf_counter() - start, 4
        ),
    }


# ---------------------------------------------------------------------
# pdfplumber extractor (fallback)
# ---------------------------------------------------------------------

def extract_with_pdfplumber(
    pdf_path: str | Path,
) -> ExtractionResult:
    """
    Extract text and metadata using pdfplumber.

    Used as a fallback when PyMuPDF extraction fails.

    Note:
        pdfplumber's text line count is not equivalent to PyMuPDF's
        text block count, so block_count is None.
    """

    import pdfplumber

    path = Path(pdf_path)
    start = time.perf_counter()

    pages: list[PageData] = []

    with pdfplumber.open(path) as pdf:

        for page_num, page in enumerate(pdf.pages, start=1):

            text = (page.extract_text() or "").strip()

            pages.append({
                "page_num": page_num,
                "text": text,
                "word_count": len(text.split()),
                "block_count": None,
                "image_count": None,
            })

        metadata = normalize_metadata(pdf.metadata, format="PDF")
        total_pages = len(pdf.pages)

    return {
        "file": str(path),
        "extractor": "pdfplumber",
        "total_pages": total_pages,
        "pages": pages,
        "metadata": metadata,
        "image_count": None,
        "extraction_time_s": round(
            time.perf_counter() - start, 4
        ),
    }


# ---------------------------------------------------------------------
# Main extraction function with fallback
# ---------------------------------------------------------------------
def extract_text_from_pdf(
    pdf_path: str | Path,
    count_images: bool = False,
    use_fallback: bool = True,
) -> ExtractionResult:
    """
    Extract a PDF using PyMuPDF, falling back to pdfplumber
    if the primary extraction fails.

    Returns an error result if both extraction methods fail.
    """
    try:
        return extract_with_pymupdf(
            pdf_path,
            count_images=count_images,
        )

    except Exception as primary_error:  # noqa: BLE001 - Parser failures use the error-result contract.

        if not use_fallback:
            logfire.exception("PDF extraction failed; fallback disabled")
            return {
                "file": str(pdf_path),
                "error": str(primary_error),
                "errors": {
                    "pymupdf": str(primary_error),
                },
            }

        logfire.warning(
            "Primary PDF extractor failed; attempting fallback",
            primary_extractor="pymupdf",
            fallback_extractor="pdfplumber",
            error_type=type(primary_error).__name__,
        )
        try:
            result = extract_with_pdfplumber(pdf_path)
            if count_images:
                logfire.warning(
                    "Image resource counting unavailable in pdfplumber fallback"
                )
            return result

        except Exception as fallback_error:  # noqa: BLE001 - Preserve errors from both parsers.

            logfire.exception("Both PDF extraction methods failed")

            return {
                "file": str(pdf_path),
                "error": "All PDF extraction methods failed.",
                "errors": {
                    "pymupdf": str(primary_error),
                    "pdfplumber": str(fallback_error),
                },
            }