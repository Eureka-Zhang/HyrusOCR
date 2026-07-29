from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from app.router import (
    ContentHint,
    Detection,
    DocumentKind,
    Processor,
    UnsupportedDocumentError,
    decide_route,
    detect_document,
    looks_like_document_scan,
)


class DetectionTests(unittest.TestCase):
    def test_pdf_magic_bytes_win_over_filename(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".jpg") as stream:
            stream.write(b"%PDF-1.7\n")
            stream.flush()
            detection = detect_document(Path(stream.name), "wrong.jpg")
        self.assertEqual(detection.kind, DocumentKind.PDF)
        self.assertEqual(detection.detected_by, "magic-bytes")

    def test_png_magic_bytes(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".bin") as stream:
            stream.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
            stream.flush()
            detection = detect_document(Path(stream.name), "upload.bin")
        self.assertEqual(detection.kind, DocumentKind.IMAGE)
        self.assertEqual(detection.media_type, "image/png")

    def test_ooxml_content_detection(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".zip") as stream:
            with zipfile.ZipFile(stream.name, "w") as archive:
                archive.writestr("[Content_Types].xml", "<Types/>")
                archive.writestr("xl/workbook.xml", "<workbook/>")
            detection = detect_document(Path(stream.name), "unknown.zip")
        self.assertEqual(detection.kind, DocumentKind.XLSX)
        self.assertEqual(detection.detected_by, "ooxml-content")


class RoutingTests(unittest.TestCase):
    def detection(self, kind: DocumentKind) -> Detection:
        return Detection(kind, "test/type", "test")

    def test_office_routes_to_native_converter(self) -> None:
        decision = decide_route(self.detection(DocumentKind.DOCX))
        self.assertEqual(decision.processor, Processor.OFFICE.value)

    def test_pdf_routes_to_structure(self) -> None:
        decision = decide_route(self.detection(DocumentKind.PDF))
        self.assertEqual(decision.processor, Processor.STRUCTURE.value)

    def test_scene_hint_routes_to_ocr(self) -> None:
        decision = decide_route(
            self.detection(DocumentKind.IMAGE),
            hint=ContentHint.SCENE.value,
            image_size=(2480, 3508),
        )
        self.assertEqual(decision.processor, Processor.OCR.value)

    def test_complex_hint_routes_to_vl(self) -> None:
        decision = decide_route(
            self.detection(DocumentKind.IMAGE),
            hint=ContentHint.COMPLEX.value,
        )
        self.assertEqual(decision.processor, Processor.VL.value)

    def test_document_shaped_image_routes_to_structure(self) -> None:
        decision = decide_route(
            self.detection(DocumentKind.IMAGE),
            image_size=(2480, 3508),
        )
        self.assertEqual(decision.processor, Processor.STRUCTURE.value)

    def test_small_image_routes_to_ocr(self) -> None:
        decision = decide_route(
            self.detection(DocumentKind.IMAGE),
            image_size=(640, 480),
        )
        self.assertEqual(decision.processor, Processor.OCR.value)

    def test_invalid_office_override_is_rejected(self) -> None:
        with self.assertRaises(UnsupportedDocumentError):
            decide_route(
                self.detection(DocumentKind.IMAGE),
                override=Processor.OFFICE.value,
            )

    def test_document_scan_heuristic(self) -> None:
        self.assertTrue(looks_like_document_scan((2480, 3508)))
        self.assertFalse(looks_like_document_scan((800, 1200)))


if __name__ == "__main__":
    unittest.main()
