from typing import Any, TypedDict


class PageData(TypedDict):
    page_num: int
    text: str
    word_count: int
    block_count: int | None
    image_count: int | None


class ExtractionResult(TypedDict, total=False):
    file: str
    extractor: str
    total_pages: int
    pages: list[PageData]
    metadata: dict[str, Any]
    image_count: int | None
    extraction_time_s: float
    error: str
    errors: dict[str, str]
