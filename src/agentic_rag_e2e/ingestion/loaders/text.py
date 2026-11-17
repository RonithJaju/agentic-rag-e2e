import time
from pathlib import Path

import logfire

from .schemas import ExtractionResult, PageData, normalize_metadata

def extract_text_from_file(path: str) -> ExtractionResult:
    start = time.perf_counter()
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            text = f.read().strip()

            page : PageData = {
                "page_num": 1,
                "text": text,
                "word_count": len(text.split()),
                "block_count": len(text.splitlines()),
                "image_count": None,
            }
            return {
                "file": str(path),
                "extractor": "text",
                "total_pages": 1,
                "pages": [page],
                "metadata":  normalize_metadata({"title": Path(path).name}, format="TXT"),
                "image_count": None,
                "extraction_time_s": round(
                    time.perf_counter() - start, 4
                )
            }
    except Exception as e:
        logfire.exception("Text extraction failed")
        return {
            "file": str(path),
            "error": "Text extraction method failed.",
            "errors": {
                "text": str(e),
            },
        }
