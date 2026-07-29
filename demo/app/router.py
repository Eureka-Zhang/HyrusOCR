from __future__ import annotations

import mimetypes
import zipfile
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


class UnsupportedDocumentError(ValueError):
    """Raised when the demo cannot route an uploaded file."""


class DocumentKind(str, Enum):
    DOCX = "docx"
    XLSX = "xlsx"
    PPTX = "pptx"
    PDF = "pdf"
    IMAGE = "image"
    UNKNOWN = "unknown"


class Processor(str, Enum):
    AUTO = "auto"
    OFFICE = "office"
    OCR = "ocr"
    STRUCTURE = "structure"
    VL = "vl"


class ContentHint(str, Enum):
    AUTO = "auto"
    SCENE = "scene"
    DOCUMENT = "document"
    COMPLEX = "complex"


@dataclass(frozen=True)
class Detection:
    kind: DocumentKind
    media_type: str
    detected_by: str


@dataclass(frozen=True)
class RouteDecision:
    processor: str
    processor_name: str
    reason: str
    kind: str
    media_type: str
    detected_by: str
    alternatives: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


_OFFICE_PROCESSORS = {
    DocumentKind.DOCX,
    DocumentKind.XLSX,
    DocumentKind.PPTX,
}
_IMAGE_SUFFIXES = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".webp",
    ".tif",
    ".tiff",
    ".gif",
}
_KIND_MEDIA_TYPES = {
    DocumentKind.DOCX: (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    DocumentKind.XLSX: (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ),
    DocumentKind.PPTX: (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    ),
    DocumentKind.PDF: "application/pdf",
}
_PROCESSOR_NAMES = {
    Processor.OFFICE: "Office → Markdown",
    Processor.OCR: "PP-OCRv6",
    Processor.STRUCTURE: "PP-StructureV3",
    Processor.VL: "PaddleOCR-VL",
}


def _detect_signature(header: bytes) -> Optional[Detection]:
    if header.startswith(b"%PDF-"):
        return Detection(DocumentKind.PDF, "application/pdf", "magic-bytes")
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return Detection(DocumentKind.IMAGE, "image/png", "magic-bytes")
    if header.startswith(b"\xff\xd8\xff"):
        return Detection(DocumentKind.IMAGE, "image/jpeg", "magic-bytes")
    if header.startswith((b"GIF87a", b"GIF89a")):
        return Detection(DocumentKind.IMAGE, "image/gif", "magic-bytes")
    if header.startswith(b"BM"):
        return Detection(DocumentKind.IMAGE, "image/bmp", "magic-bytes")
    if header.startswith((b"II*\x00", b"MM\x00*")):
        return Detection(DocumentKind.IMAGE, "image/tiff", "magic-bytes")
    if len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return Detection(DocumentKind.IMAGE, "image/webp", "magic-bytes")
    return None


def _detect_ooxml(path: Path) -> Optional[Detection]:
    if not zipfile.is_zipfile(path):
        return None
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
    except (OSError, zipfile.BadZipFile):
        return None
    for member, kind in (
        ("word/document.xml", DocumentKind.DOCX),
        ("xl/workbook.xml", DocumentKind.XLSX),
        ("ppt/presentation.xml", DocumentKind.PPTX),
    ):
        if member in names:
            return Detection(kind, _KIND_MEDIA_TYPES[kind], "ooxml-content")
    return None


def detect_document(path: Path, original_name: str) -> Detection:
    with path.open("rb") as stream:
        header = stream.read(32)

    signature = _detect_signature(header)
    if signature:
        return signature

    ooxml = _detect_ooxml(path)
    if ooxml:
        return ooxml

    suffix = Path(original_name).suffix.lower()
    suffix_kinds = {
        ".docx": DocumentKind.DOCX,
        ".xlsx": DocumentKind.XLSX,
        ".pptx": DocumentKind.PPTX,
        ".pdf": DocumentKind.PDF,
    }
    if suffix in suffix_kinds:
        kind = suffix_kinds[suffix]
        return Detection(kind, _KIND_MEDIA_TYPES[kind], "filename-fallback")
    if suffix in _IMAGE_SUFFIXES:
        media_type = mimetypes.guess_type(original_name)[0] or "image/unknown"
        return Detection(DocumentKind.IMAGE, media_type, "filename-fallback")
    return Detection(
        DocumentKind.UNKNOWN,
        mimetypes.guess_type(original_name)[0] or "application/octet-stream",
        "unrecognized",
    )


def read_image_size(path: Path) -> Optional[tuple[int, int]]:
    try:
        from PIL import Image

        with Image.open(path) as image:
            return image.size
    except Exception:
        return None


def looks_like_document_scan(image_size: Optional[tuple[int, int]]) -> bool:
    if not image_size:
        return False
    width, height = image_size
    if width < 900 or height < 900:
        return False
    ratio = width / height
    return 0.55 <= ratio <= 0.85 or 1.18 <= ratio <= 1.82


def _validate_override(processor: Processor, kind: DocumentKind) -> None:
    if processor is Processor.OFFICE and kind not in _OFFICE_PROCESSORS:
        raise UnsupportedDocumentError(
            "Office 处理器只接受 DOCX、XLSX、PPTX。"
        )
    if processor in {Processor.OCR, Processor.STRUCTURE, Processor.VL} and kind not in {
        DocumentKind.IMAGE,
        DocumentKind.PDF,
    }:
        raise UnsupportedDocumentError(
            f"{_PROCESSOR_NAMES[processor]} 只接受图片或 PDF。"
        )


def decide_route(
    detection: Detection,
    *,
    override: str = "auto",
    hint: str = "auto",
    image_size: Optional[tuple[int, int]] = None,
) -> RouteDecision:
    try:
        processor = Processor(override)
    except ValueError as exc:
        raise UnsupportedDocumentError(f"未知处理器：{override}") from exc
    try:
        content_hint = ContentHint(hint)
    except ValueError as exc:
        raise UnsupportedDocumentError(f"未知内容提示：{hint}") from exc

    kind = detection.kind
    if kind is DocumentKind.UNKNOWN:
        raise UnsupportedDocumentError(
            "暂不支持该文件。Demo 支持 DOCX、XLSX、PPTX、PDF 和常见图片。"
        )

    if processor is not Processor.AUTO:
        _validate_override(processor, kind)
        selected = processor
        reason = f"调用方手动指定 {_PROCESSOR_NAMES[selected]}。"
    elif kind in _OFFICE_PROCESSORS:
        selected = Processor.OFFICE
        reason = f"检测到 {kind.value.upper()}，优先使用原生 Office 结构解析。"
    elif content_hint is ContentHint.COMPLEX:
        selected = Processor.VL
        reason = "内容提示为复杂文档，选择 PaddleOCR-VL。"
    elif kind is DocumentKind.PDF:
        selected = Processor.STRUCTURE
        reason = "检测到 PDF，Demo 默认保留版面、表格和阅读顺序。"
    elif content_hint is ContentHint.DOCUMENT:
        selected = Processor.STRUCTURE
        reason = "内容提示为文档/表格，选择 PP-StructureV3。"
    elif content_hint is ContentHint.SCENE:
        selected = Processor.OCR
        reason = "内容提示为普通图片/ROI，选择 PP-OCRv6。"
    elif looks_like_document_scan(image_size):
        selected = Processor.STRUCTURE
        width, height = image_size or (0, 0)
        reason = (
            f"图片尺寸为 {width}×{height}，外形接近文档扫描页，"
            "选择 PP-StructureV3。"
        )
    else:
        selected = Processor.OCR
        reason = "检测到普通图片，选择延迟更低的 PP-OCRv6。"

    alternatives: list[str]
    if kind in _OFFICE_PROCESSORS:
        alternatives = []
    else:
        alternatives = [
            value.value
            for value in (Processor.OCR, Processor.STRUCTURE, Processor.VL)
            if value is not selected
        ]

    return RouteDecision(
        processor=selected.value,
        processor_name=_PROCESSOR_NAMES[selected],
        reason=reason,
        kind=kind.value,
        media_type=detection.media_type,
        detected_by=detection.detected_by,
        alternatives=alternatives,
    )
