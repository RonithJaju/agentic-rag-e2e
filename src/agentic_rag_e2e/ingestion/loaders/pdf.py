
from __future__ import annotations

import logging
import time

from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from ..loaders.schemas import ExtractionResult, PageData

import pymupdf


logger = logging.getLogger(__name__)


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

        metadata = doc.metadata or {}
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
        pdfplumber's word count is not equivalent to PyMuPDF's
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

        metadata = pdf.metadata or {}
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

    except Exception as primary_error:

        logger.warning(
            "PyMuPDF extraction failed for %s: %s",
            pdf_path,
            primary_error,
        )

        if not use_fallback:
            return {
                "file": str(pdf_path),
                "error": str(primary_error),
                "errors": {
                    "pymupdf": str(primary_error),
                },
            }

        try:
            result = extract_with_pdfplumber(pdf_path)

            if count_images:
                logger.warning(
                    "Image resource counting unavailable "
                    "in pdfplumber fallback: %s",
                    pdf_path,
                )

            return result

        except Exception as fallback_error:

            logger.exception(
                "Both PDF extraction methods failed for %s",
                pdf_path,
            )

            return {
                "file": str(pdf_path),
                "error": "All PDF extraction methods failed.",
                "errors": {
                    "pymupdf": str(primary_error),
                    "pdfplumber": str(fallback_error),
                },
            }


# ---------------------------------------------------------------------
# Batch extraction worker
# ---------------------------------------------------------------------

def _batch_extract_worker(
    args: tuple[str, bool, bool],
) -> ExtractionResult:
    """
    Worker function for ProcessPoolExecutor.

    Must remain at module level to be picklable.
    """

    pdf_path, count_images, use_fallback = args

    return extract_text_from_pdf(
        pdf_path,
        count_images=count_images,
        use_fallback=use_fallback,
    )


# ---------------------------------------------------------------------
# Batch extraction
# ---------------------------------------------------------------------

def batch_extract(
    pdf_dir: str | Path,
    max_workers: int = 4,
    count_images: bool = False,
    use_fallback: bool = True,
) -> list[ExtractionResult]:
    """
    Extract all PDFs in a directory concurrently.

    Each worker processes an independent PDF.

    Results preserve the order of input files.
    """

    directory = Path(pdf_dir)

    if not directory.is_dir():
        raise NotADirectoryError(
            f"Directory not found: {directory}"
        )

    if max_workers < 1:
        raise ValueError("max_workers must be at least 1")

    pdf_files = sorted(
        directory.glob("*.pdf"),
        key=lambda path: path.name.lower(),
    )

    if not pdf_files:
        logger.info("No PDF files found in %s", directory)
        return []

    logger.info(
        "Starting batch extraction: %d PDFs, %d workers",
        len(pdf_files),
        max_workers,
    )

    worker_args = [
        (str(path), count_images, use_fallback)
        for path in pdf_files
    ]

    with ProcessPoolExecutor(
        max_workers=max_workers
    ) as executor:

        results = list(
            executor.map(
                _batch_extract_worker,
                worker_args,
            )
        )

    successful = sum(
        "error" not in result for result in results
    )

    logger.info(
        "Batch extraction completed: %d/%d successful",
        successful,
        len(results),
    )

    return results
