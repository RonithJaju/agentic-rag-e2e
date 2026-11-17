import time
from pathlib import Path

import logfire
from unstructured.partition.auto import partition

from .schemas import ExtractionResult, PageData, normalize_metadata


def extract_text_from_office_file(path: str) -> ExtractionResult:
    start = time.perf_counter()
    try:
        elements = partition(filename=path)

        page_data: list[PageData] = []
        for element in elements:
            page_num = element.metadata.page_number or 1
            text = "\n".join(element.text.strip()) or ""
            page_data.append({
                "page_num": page_num,
                "text": text,
                "word_count": len(text.split()),
                "block_count": None,
                "image_count": None,
            })

        return {
            "file": str(path),
            "extractor": "office",
            "total_pages": len(page_data),
            "pages": page_data,
            "metadata": normalize_metadata(
                {"title": Path(path).name},
                format=Path(path).suffix.lstrip(".").upper() or None,
            ),
            "image_count": None,
            "extraction_time_s": round(
                time.perf_counter() - start, 4
            ),
        }
    except Exception as e:
        logfire.exception("Office extraction failed")
        return {
            "file": str(path),
            "error": "Office extraction method failed.",
            "errors": {
                "office": str(e),
            },
        }