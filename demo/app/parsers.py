from __future__ import annotations

import os
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Optional


class ParsingError(RuntimeError):
    """Raised when a selected parser cannot process the document."""


@dataclass
class ParsedOutput:
    markdown: str
    pages: int
    data: Any
    model: str
    mock: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _to_builtin(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _to_builtin(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_builtin(item) for item in value]
    if hasattr(value, "tolist"):
        try:
            return _to_builtin(value.tolist())
        except Exception:
            pass
    if hasattr(value, "model_dump"):
        try:
            return _to_builtin(value.model_dump())
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        return {
            str(key): _to_builtin(item)
            for key, item in vars(value).items()
            if not str(key).startswith("_")
        }
    return str(value)


def _result_json(result: Any) -> Any:
    value = getattr(result, "json", None)
    if callable(value):
        value = value()
    if value is not None:
        return _to_builtin(value)
    if isinstance(result, Mapping):
        return _to_builtin(dict(result))
    return _to_builtin(result)


def _find_values(value: Any, key: str) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, Mapping):
        for current_key, current_value in value.items():
            if current_key == key:
                found.append(current_value)
            found.extend(_find_values(current_value, key))
    elif isinstance(value, list):
        for item in value:
            found.extend(_find_values(item, key))
    return found


def _extract_ocr_markdown(data: Any) -> str:
    text_groups = _find_values(data, "rec_texts")
    lines: list[str] = []
    for group in text_groups:
        if isinstance(group, list):
            for item in group:
                text = str(item).strip()
                if text and text not in lines:
                    lines.append(text)
    return "\n\n".join(lines)


def _markdown_dict(result: Any) -> Optional[dict]:
    value = getattr(result, "markdown", None)
    if callable(value):
        value = value()
    return value if isinstance(value, dict) else None


def _markdown_text(value: Optional[dict]) -> str:
    if not value:
        return ""
    for key in ("markdown_texts", "markdown_text", "text"):
        text = value.get(key)
        if isinstance(text, str):
            return text
    return ""


class PipelineManager:
    def __init__(self) -> None:
        self._pipelines: dict[str, Any] = {}
        self._lock = threading.Lock()

    @property
    def loaded(self) -> list[str]:
        return sorted(self._pipelines)

    def get(self, processor: str) -> Any:
        with self._lock:
            if processor not in self._pipelines:
                self._pipelines[processor] = self._create(processor)
            return self._pipelines[processor]

    @staticmethod
    def _create(processor: str) -> Any:
        try:
            from paddleocr import PaddleOCR, PaddleOCRVL, PPStructureV3
        except Exception as exc:
            raise ParsingError(
                "无法导入 PaddleOCR 推理依赖。请先按 demo/README.md 安装 "
                "PaddlePaddle 与 paddleocr[all]。"
            ) from exc

        device = os.getenv("HYRUS_DEMO_DEVICE", "cpu")
        if processor == "ocr":
            return PaddleOCR(
                ocr_version="PP-OCRv6",
                device=device,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        if processor == "structure":
            kwargs: dict[str, Any] = {"device": device}
            disabled = {
                item.strip()
                for item in os.getenv("HYRUS_DEMO_STRUCTURE_DISABLE", "").split(",")
                if item.strip()
            }
            submodel_flags = {
                "formula": "use_formula_recognition",
                "table": "use_table_recognition",
                "chart": "use_chart_recognition",
                "seal": "use_seal_recognition",
                "region": "use_region_detection",
            }
            for name, flag in submodel_flags.items():
                if name in disabled:
                    kwargs[flag] = False
            return PPStructureV3(**kwargs)
        if processor == "vl":
            kwargs: dict[str, Any] = {"device": device}
            backend = os.getenv("HYRUS_DEMO_VL_BACKEND")
            server_url = os.getenv("HYRUS_DEMO_VL_SERVER_URL")
            if backend:
                kwargs["vl_rec_backend"] = backend
            if server_url:
                kwargs["vl_rec_server_url"] = server_url
            return PaddleOCRVL(**kwargs)
        raise ParsingError(f"未知推理处理器：{processor}")


PIPELINES = PipelineManager()


def _parse_office(path: Path) -> ParsedOutput:
    try:
        from paddleocr import doc2md_convert

        result = doc2md_convert(path)
    except Exception as exc:
        raise ParsingError(f"Office 转换失败：{exc}") from exc

    data = {
        "metadata": _to_builtin(result.metadata),
        "embedded_images": sorted(result.images),
    }
    return ParsedOutput(
        markdown=result.markdown,
        pages=1,
        data=data,
        model="paddleocr-doc2md",
    )


def _parse_ocr(path: Path) -> ParsedOutput:
    pipeline = PIPELINES.get("ocr")
    try:
        results = list(pipeline.predict(str(path)))
    except Exception as exc:
        raise ParsingError(f"PP-OCRv6 推理失败：{exc}") from exc

    data = [_result_json(result) for result in results]
    return ParsedOutput(
        markdown=_extract_ocr_markdown(data),
        pages=len(results),
        data=data,
        model="PP-OCRv6",
    )


def _parse_document_pipeline(path: Path, processor: str) -> ParsedOutput:
    pipeline = PIPELINES.get(processor)
    try:
        results = list(pipeline.predict(str(path)))
    except Exception as exc:
        label = "PP-StructureV3" if processor == "structure" else "PaddleOCR-VL"
        raise ParsingError(f"{label} 推理失败：{exc}") from exc

    markdown_objects = [
        markdown
        for result in results
        if (markdown := _markdown_dict(result)) is not None
    ]
    markdown = ""
    if markdown_objects:
        try:
            concatenated = pipeline.concatenate_markdown_pages(markdown_objects)
            if isinstance(concatenated, str):
                markdown = concatenated
            else:
                # paddlex returns a MarkdownResult (dict-like with markdown_texts)
                markdown = _markdown_text(_markdown_dict(concatenated))
        except Exception:
            markdown = ""
        if not markdown:
            markdown = "\n\n".join(
                text for item in markdown_objects if (text := _markdown_text(item))
            )

    data = [_result_json(result) for result in results]
    model = "PP-StructureV3" if processor == "structure" else "PaddleOCR-VL"
    return ParsedOutput(
        markdown=markdown,
        pages=len(results),
        data=data,
        model=model,
    )


def _mock_parse(
    path: Path,
    processor: str,
    source_name: Optional[str] = None,
) -> ParsedOutput:
    labels = {
        "office": "paddleocr-doc2md",
        "ocr": "PP-OCRv6",
        "structure": "PP-StructureV3",
        "vl": "PaddleOCR-VL",
    }
    markdown = (
        "# HyrusOCR Demo\n\n"
        f"- 文件：`{source_name or path.name}`\n"
        f"- 路由处理器：`{labels[processor]}`\n"
        "- 当前为 Mock 模式，已跳过模型推理。"
    )
    return ParsedOutput(
        markdown=markdown,
        pages=1,
        data={
            "mock": True,
            "processor": processor,
            "filename": source_name or path.name,
        },
        model=labels[processor],
        mock=True,
    )


def parse_document(
    path: Path,
    processor: str,
    source_name: Optional[str] = None,
) -> ParsedOutput:
    if os.getenv("HYRUS_DEMO_MOCK", "").lower() in {"1", "true", "yes"}:
        return _mock_parse(path, processor, source_name)
    if processor == "office":
        return _parse_office(path)
    if processor == "ocr":
        return _parse_ocr(path)
    if processor in {"structure", "vl"}:
        return _parse_document_pipeline(path, processor)
    raise ParsingError(f"未知处理器：{processor}")
