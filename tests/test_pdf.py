import importlib
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

import logfire
import pymupdf
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from agentic_rag_e2e.observability import install_auto_tracing

install_auto_tracing()
pdf = importlib.import_module("agentic_rag_e2e.ingestion.loaders.pdf")


def span_name(function: str) -> str:
    return f"Calling {pdf.__name__}.{function}"


class PDFObservabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.exporter = InMemorySpanExporter()
        logfire.configure(
            send_to_logfire=False,
            console=False,
            metrics=False,
            additional_span_processors=[SimpleSpanProcessor(cls.exporter)],
        )

    def setUp(self) -> None:
        self.exporter.clear()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "document.pdf"

    def create_pdf(self) -> None:
        with pymupdf.open() as document:
            page = document.new_page()
            page.insert_text((72, 72), "A PDF for extraction tests.")
            document.save(self.path)

    def test_primary_success_has_timed_child_span_without_document_attributes(self) -> None:
        self.create_pdf()

        result = pdf.extract_text_from_pdf(self.path, count_images=True)

        self.assertEqual(result["extractor"], "pymupdf")
        self.assertEqual(result["total_pages"], 1)
        self.assertIn("A PDF for extraction tests.", result["pages"][0]["text"])
        spans = self.exporter.get_finished_spans()
        parent = next(span for span in spans if span.name == span_name("extract_text_from_pdf"))
        child = next(span for span in spans if span.name == span_name("extract_with_pymupdf"))
        self.assertIsNotNone(parent.context)
        self.assertIsNotNone(child.parent)
        assert parent.context is not None
        assert child.parent is not None
        self.assertEqual(child.parent.span_id, parent.context.span_id)
        self.assertNotEqual(parent.status.status_code, StatusCode.ERROR)
        self.assertGreater(child.end_time, child.start_time)
        for span in (parent, child):
            self.assertNotIn("pdf_path", span.attributes)
            self.assertNotIn("pages", span.attributes)

    def test_both_pdf_extractors_normalize_document_metadata(self) -> None:
        expected = {
            "title": "Annual Report",
            "author": "Jane Doe",
            "subject": "Financials",
            "keywords": "finance, Q4",
            "creator": "Report builder",
            "producer": "PDF generator",
            "creationDate": "D:20261117120000Z",
            "modDate": "D:20261117123000Z",
        }
        with pymupdf.open() as document:
            document.new_page().insert_text((72, 72), "Report body")
            document.set_metadata(expected)
            document.save(self.path)

        for extractor in (pdf.extract_with_pymupdf, pdf.extract_with_pdfplumber):
            with self.subTest(extractor=extractor.__name__):
                result = extractor(self.path)

                metadata = result["metadata"]
                self.assertEqual(
                    set(metadata), set(expected) | {"format", "trapped", "encryption"}
                )
                for field, value in expected.items():
                    self.assertEqual(metadata[field], value)
                self.assertTrue(metadata["format"].startswith("PDF"))
                self.assertIsNone(metadata["encryption"])
                self.assertEqual(result["pages"][0]["text"], "Report body")

    def test_fallback_records_failure_and_image_count_limitation(self) -> None:
        self.create_pdf()

        with patch.object(pymupdf, "open", side_effect=RuntimeError("primary failed")):
            result = pdf.extract_text_from_pdf(self.path, count_images=True)

        self.assertEqual(result["extractor"], "pdfplumber")
        self.assertIsNone(result["pages"][0]["block_count"])
        self.assertIsNone(result["image_count"])
        spans = self.exporter.get_finished_spans()
        parent = next(span for span in spans if span.name == span_name("extract_text_from_pdf"))
        primary = next(span for span in spans if span.name == span_name("extract_with_pymupdf"))
        fallback = next(span for span in spans if span.name == span_name("extract_with_pdfplumber"))
        self.assertNotEqual(parent.status.status_code, StatusCode.ERROR)
        self.assertEqual(primary.status.status_code, StatusCode.ERROR)
        self.assertTrue(primary.events)
        self.assertEqual(fallback.parent.span_id, parent.context.span_id)
        messages = [span.name for span in spans]
        self.assertIn("Primary PDF extractor failed; attempting fallback", messages)
        self.assertIn("Image resource counting unavailable in pdfplumber fallback", messages)

    def test_terminal_failures_are_recorded_without_changing_error_results(self) -> None:
        for use_fallback in (False, True):
            with self.subTest(use_fallback=use_fallback):
                self.exporter.clear()

                result = pdf.extract_text_from_pdf(
                    self.path, use_fallback=use_fallback
                )

                self.assertIn("error", result)
                self.assertEqual(
                    set(result["errors"]),
                    {"pymupdf", "pdfplumber"} if use_fallback else {"pymupdf"},
                )
                spans = self.exporter.get_finished_spans()
                parent = next(
                    span for span in spans
                    if span.name == span_name("extract_text_from_pdf")
                )
                self.assertNotEqual(parent.status.status_code, StatusCode.ERROR)
                message = (
                    "Both PDF extraction methods failed"
                    if use_fallback else "PDF extraction failed; fallback disabled"
                )
                error = next(span for span in spans if span.name == message)
                self.assertEqual(error.attributes["logfire.level_num"], 17)
                self.assertTrue(error.events)
                self.assertEqual(error.parent.span_id, parent.context.span_id)

    def test_empty_batch_records_an_event_under_the_batch_span(self) -> None:
        self.assertEqual(pdf.batch_extract(self.directory.name), [])

        spans = self.exporter.get_finished_spans()
        batch = next(span for span in spans if span.name == span_name("batch_extract"))
        event = next(span for span in spans if span.name == "No PDF files found")
        self.assertEqual(event.parent.span_id, batch.context.span_id)

    def test_batch_records_structured_counts_and_preserves_input_order(self) -> None:
        self.create_pdf()
        second_path = self.path.with_name("another.pdf")
        second_path.write_bytes(self.path.read_bytes())

        with patch.object(pdf, "ProcessPoolExecutor") as executor:
            executor.return_value.__enter__.return_value.map.side_effect = (
                lambda worker, args: map(worker, args)
            )
            results = pdf.batch_extract(self.directory.name, max_workers=1)

        self.assertEqual(
            [result["file"] for result in results],
            [str(second_path), str(self.path)],
        )
        spans = self.exporter.get_finished_spans()
        batch = next(span for span in spans if span.name == span_name("batch_extract"))
        completed = next(
            span for span in spans if span.name == "Batch extraction completed"
        )
        self.assertEqual(completed.attributes["successful"], 2)
        self.assertEqual(completed.attributes["failed"], 0)
        self.assertEqual(completed.attributes["total"], 2)
        workers = {
            span.context.span_id: span
            for span in spans
            if span.name == span_name("_batch_extract_worker")
        }
        self.assertEqual(len(workers), 2)
        for worker in workers.values():
            self.assertEqual(worker.parent.span_id, batch.context.span_id)
        for span in spans:
            if span.name == span_name("extract_text_from_pdf"):
                self.assertIn(span.parent.span_id, workers)

    def test_auto_tracing_is_installed_in_spawned_batch_workers(self) -> None:
        self.create_pdf()
        runner = Path(self.directory.name) / "run_batch.py"
        runner.write_text(
            textwrap.dedent(
                """\
                import sys

                import logfire

                from agentic_rag_e2e.observability import install_auto_tracing

                install_auto_tracing()

                from agentic_rag_e2e.ingestion.loaders.pdf import batch_extract

                if __name__ == "__main__":
                    logfire.configure(
                        send_to_logfire=False,
                        console=logfire.ConsoleOptions(
                            colors="never",
                            span_style="indented",
                            include_timestamps=False,
                        ),
                        metrics=False,
                    )
                    results = batch_extract(sys.argv[1], max_workers=1)
                    assert len(results) == 1
                    assert results[0]["extractor"] == "pymupdf"
                    assert results[0]["total_pages"] == 1
                    logfire.force_flush()
                """
            ),
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment["LOGFIRE_SEND_TO_LOGFIRE"] = "false"
        environment["COLUMNS"] = "240"

        completed = subprocess.run(
            [sys.executable, str(runner), self.directory.name],
            capture_output=True,
            text=True,
            timeout=60,
            env=environment,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        output = completed.stdout + completed.stderr
        self.assertIn(span_name("batch_extract"), output)
        self.assertIn(span_name("_batch_extract_worker"), output)
        self.assertIn(span_name("extract_with_pymupdf"), output)
        self.assertNotIn("cannot be pickled", output)


if __name__ == "__main__":
    unittest.main()
