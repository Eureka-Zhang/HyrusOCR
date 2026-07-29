from __future__ import annotations

import os
import tempfile
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from .parsers import PIPELINES, ParsingError, parse_document
from .router import (
    UnsupportedDocumentError,
    decide_route,
    detect_document,
    read_image_size,
)


APP_DIR = Path(__file__).resolve().parent
INDEX_FILE = APP_DIR / "static" / "index.html"
MAX_UPLOAD_BYTES = int(os.getenv("HYRUS_DEMO_MAX_UPLOAD_MB", "25")) * 1024 * 1024

app = FastAPI(
    title="HyrusOCR Routing Demo",
    version="0.1.0",
    description="输入 → 文件识别 → 路由 → PaddleOCR 解析 → Markdown/JSON 输出",
)


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(INDEX_FILE)


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "mock": os.getenv("HYRUS_DEMO_MOCK", "").lower()
        in {"1", "true", "yes"},
        "device": os.getenv("HYRUS_DEMO_DEVICE", "cpu"),
        "loaded_processors": PIPELINES.loaded,
    }


@app.get("/api/v1/rules")
async def rules() -> dict:
    return {
        "rules": [
            {
                "priority": 1,
                "match": "DOCX / XLSX / PPTX",
                "processor": "office",
                "name": "Office → Markdown",
            },
            {
                "priority": 2,
                "match": "复杂文档提示",
                "processor": "vl",
                "name": "PaddleOCR-VL",
            },
            {
                "priority": 3,
                "match": "PDF、文档/表格提示、文档扫描页外形",
                "processor": "structure",
                "name": "PP-StructureV3",
            },
            {
                "priority": 4,
                "match": "普通图片 / ROI",
                "processor": "ocr",
                "name": "PP-OCRv6",
            },
        ],
        "note": "调用方可通过 processor 参数手动覆盖自动路由。",
    }


async def _save_upload(upload: UploadFile) -> tuple[Path, int]:
    original_name = upload.filename or "upload.bin"
    suffix = Path(original_name).suffix[:16]
    temp_file = tempfile.NamedTemporaryFile(
        prefix="hyrusocr-",
        suffix=suffix,
        delete=False,
    )
    temp_path = Path(temp_file.name)
    total = 0
    try:
        while chunk := await upload.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"文件超过 Demo 限制："
                        f"{MAX_UPLOAD_BYTES // 1024 // 1024} MB。"
                    ),
                )
            temp_file.write(chunk)
        temp_file.close()
        if total == 0:
            raise HTTPException(status_code=400, detail="上传文件为空。")
        return temp_path, total
    except Exception:
        temp_file.close()
        temp_path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()


@app.post("/api/v1/parse")
async def parse(
    file: UploadFile = File(...),
    processor: str = Form("auto"),
    hint: str = Form("auto"),
    dry_run: bool = Form(False),
) -> dict:
    request_id = str(uuid.uuid4())
    started = time.perf_counter()
    original_name = file.filename or "upload.bin"
    temp_path, size = await _save_upload(file)
    try:
        detection = await run_in_threadpool(
            detect_document,
            temp_path,
            original_name,
        )
        image_size = None
        if detection.kind.value == "image":
            image_size = await run_in_threadpool(read_image_size, temp_path)
        decision = decide_route(
            detection,
            override=processor,
            hint=hint,
            image_size=image_size,
        )

        output = None
        if not dry_run:
            parsed = await run_in_threadpool(
                parse_document,
                temp_path,
                decision.processor,
                original_name,
            )
            output = parsed.to_dict()

        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        return {
            "request_id": request_id,
            "status": "routed" if dry_run else "succeeded",
            "elapsed_ms": elapsed_ms,
            "file": {
                "name": original_name,
                "size_bytes": size,
                "image_size": image_size,
            },
            "route": decision.to_dict(),
            "output": output,
        }
    except UnsupportedDocumentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ParsingError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Demo 处理失败：{exc}",
        ) from exc
    finally:
        temp_path.unlink(missing_ok=True)
