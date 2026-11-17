from collections.abc import Mapping
from typing import TypedDict


class MetaData(TypedDict):
    format: str | None
    title: str | None
    author: str | None
    subject: str | None
    keywords: str | None
    creator: str | None
    producer: str | None
    creationDate: str | None
    modDate: str | None
    trapped: str | None
    encryption: str | None


def normalize_metadata(
    source: Mapping[str, object] | None = None,
    *,
    format: str | None = None,
) -> MetaData:
    """Normalize native metadata names and fill unavailable fields with None."""
    values = {key.lower(): value for key, value in (source or {}).items()}

    def value(key: str) -> str | None:
        item = values.get(key.lower())
        if item is None or isinstance(item, str):
            return item
        if key == "trapped" and isinstance(item, bool):
            return str(item)
        raise TypeError(f"Metadata field {key!r} must be a string or None")

    return MetaData(
        format=value("format") or format,
        title=value("title"),
        author=value("author"),
        subject=value("subject"),
        keywords=value("keywords"),
        creator=value("creator"),
        producer=value("producer"),
        creationDate=value("creationDate"),
        modDate=value("modDate"),
        trapped=value("trapped"),
        encryption=value("encryption"),
    )


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
    metadata: MetaData
    image_count: int | None
    extraction_time_s: float
    error: str
    errors: dict[str, str]
