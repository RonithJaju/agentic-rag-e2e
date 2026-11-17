import time

import logfire
from bs4 import BeautifulSoup
from .schemas import PageData, ExtractionResult, normalize_metadata

def extract_html(path: str) -> ExtractionResult:
    start = time.perf_counter()
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        
        soup = BeautifulSoup(text, "html.parser")
        
        # Extract MetaData
        html_metadata: dict[str, object] = {
            "title": soup.title.get_text(strip=True) if soup.title else None,
        }
        fields = {
            "author": "author",
            "description": "subject",
            "keywords": "keywords",
            "generator": "creator",
        }
        for tag in soup.find_all("meta"):
            name = tag.get("name")
            if isinstance(name, str) and name.lower() in fields:
                html_metadata[fields[name.lower()]] = tag.get("content")
        metadata = normalize_metadata(html_metadata, format="HTML")
        
        for tag in soup(["script", "style", "meta", "noscript"]):
            tag.decompose()

        cleaned_text = soup.get_text(separator="\n", strip=True)
        return ExtractionResult(
            file=path,
            extractor="html",
            total_pages=1,
            pages=[
                PageData(
                    page_num=1,
                    text=cleaned_text,
                    word_count=len(cleaned_text.split()),
                    block_count=None,
                    image_count=None,
                )
            ],
            metadata=metadata,
            image_count=None,
            extraction_time_s=round(time.perf_counter() - start, 4)
        )
    except Exception as e:  # noqa: BLE001 - Parser failures use the error-result contract.
        logfire.exception("HTML extraction method failed")

        return {
            "file": str(path),
            "error": "HTML extraction method failed.",
            "errors": {
                "html": str(e),
            },
        }


        