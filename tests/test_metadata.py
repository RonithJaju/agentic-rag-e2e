import importlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agentic_rag_e2e.observability import install_auto_tracing

install_auto_tracing()
schemas = importlib.import_module("agentic_rag_e2e.ingestion.loaders.schemas")
html = importlib.import_module("agentic_rag_e2e.ingestion.loaders.html")
text = importlib.import_module("agentic_rag_e2e.ingestion.loaders.text")


class MetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    def assert_metadata_shape(self, metadata: dict) -> None:
        self.assertEqual(
            set(metadata),
            {
                "format", "title", "author", "subject", "keywords", "creator",
                "producer", "creationDate", "modDate", "trapped", "encryption",
            },
        )
        self.assertTrue(
            all(value is None or isinstance(value, str) for value in metadata.values())
        )
        json.dumps(metadata)

    def test_text_metadata_has_nullable_document_fields_not_filesystem_dates(self) -> None:
        path = self.directory / "notes.txt"
        path.write_text("First line\nSecond line", encoding="utf-8")

        result = text.extract_text_from_file(str(path))

        metadata = result["metadata"]
        self.assert_metadata_shape(metadata)
        self.assertEqual(metadata["format"], "TXT")
        self.assertEqual(metadata["title"], "notes.txt")
        for field in set(metadata) - {"format", "title"}:
            self.assertIsNone(metadata[field])
        self.assertEqual(result["pages"][0]["text"], "First line\nSecond line")

    def test_html_reads_metadata_before_removing_tags(self) -> None:
        path = self.directory / "report.html"
        path.write_text(
            """<html><head><title>Annual &amp; quarterly report</title>
            <meta name="AUTHOR" content="Jane Doe">
            <meta name="description" content="Financials">
            <meta name="keywords" content="finance, Q4">
            <meta name="generator" content="Report builder">
            <style>body { color: red; }</style>
            <script>alert("not content");</script></head>
            <body><p>Revenue increased.</p></body></html>""",
            encoding="utf-8",
        )

        result = html.extract_html(str(path))

        metadata = result["metadata"]
        self.assert_metadata_shape(metadata)
        self.assertEqual(metadata["format"], "HTML")
        self.assertEqual(metadata["title"], "Annual & quarterly report")
        self.assertEqual(metadata["author"], "Jane Doe")
        self.assertEqual(metadata["subject"], "Financials")
        self.assertEqual(metadata["keywords"], "finance, Q4")
        self.assertEqual(metadata["creator"], "Report builder")
        self.assertIsNone(metadata["creationDate"])
        self.assertEqual(
            result["pages"][0]["text"],
            "Annual & quarterly report\nRevenue increased.",
        )

    def test_html_missing_metadata_stays_null(self) -> None:
        path = self.directory / "minimal.html"
        path.write_text('<meta name="author"><p>Body</p>', encoding="utf-8")

        metadata = html.extract_html(str(path))["metadata"]

        self.assert_metadata_shape(metadata)
        for field in set(metadata) - {"format"}:
            self.assertIsNone(metadata[field])

    @unittest.skipUnless(
        importlib.util.find_spec("unstructured") is not None,
        "Office extraction requires the unstructured dependency",
    )
    def test_office_metadata_is_consistent_for_empty_and_populated_documents(self) -> None:
        office = importlib.import_module("agentic_rag_e2e.ingestion.loaders.office")
        element = SimpleNamespace(
            text="Office text",
            metadata=SimpleNamespace(page_number=1),
        )
        for elements in ([], [element]):
            with self.subTest(elements=elements):
                with patch.object(office, "partition", return_value=elements):
                    result = office.extract_text_from_office_file(
                        str(self.directory / "report.docx")
                    )

                metadata = result["metadata"]
                self.assert_metadata_shape(metadata)
                self.assertEqual(metadata["format"], "DOCX")
                self.assertEqual(metadata["title"], "report.docx")
                self.assertIsNone(metadata["author"])
                self.assertIsNone(metadata["modDate"])

    def test_normalization_handles_native_keys_without_leaking_extra_fields(self) -> None:
        metadata = schemas.normalize_metadata(
            {
                "Title": "Report",
                "CreationDate": "D:20261117120000Z",
                "Trapped": False,
                "CustomField": ["not part of the schema"],
            },
            format="PDF",
        )
        self.assert_metadata_shape(metadata)
        self.assertEqual(metadata["title"], "Report")
        self.assertEqual(metadata["creationDate"], "D:20261117120000Z")
        self.assertEqual(metadata["trapped"], "False")
        self.assertIsNone(metadata["author"])
        with self.assertRaisesRegex(TypeError, "title"):
            schemas.normalize_metadata({"Title": ["invalid"]})


if __name__ == "__main__":
    unittest.main()
