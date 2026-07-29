# HyrusOCR Routing Demo

一个最小可请求 Demo，展示：

1. 上传 DOCX、XLSX、PPTX、PDF 或图片；
2. 根据文件真实内容、内容提示和图片尺寸选择处理器；
3. 调用 Office 转换、PP-OCRv6、PP-StructureV3 或 PaddleOCR-VL；
4. 在网页或 JSON API 中返回路由决策、Markdown 和原始 JSON。

这不是生产服务：当前为同步请求，不包含鉴权、队列、数据库、对象存储和质量回退。

## 路由规则

| 优先级 | 条件 | 处理器 |
| --- | --- | --- |
| 1 | DOCX / XLSX / PPTX | Office → Markdown |
| 2 | `hint=complex` | PaddleOCR-VL |
| 3 | PDF、`hint=document`、外形接近扫描页的高清图片 | PP-StructureV3 |
| 4 | 普通图片、`hint=scene` | PP-OCRv6 |

`processor=office|ocr|structure|vl` 可以覆盖自动路由。

## 安装

推荐 Python 3.11。先在仓库根目录安装 PaddleOCR 与推理引擎，再安装 Demo 依赖。

如果机器上已有 conda，建议用 conda 固定 Python 版本：

```bash
cd /Users/eureka/Desktop/HyrusOCR
conda create -n hyrusocr python=3.11 -y
conda activate hyrusocr
python -m pip install -U pip
python -m pip install -e ".[all]"
python -m pip install -r demo/requirements.txt
```

如果机器本身已经有合适的 Python，可以使用 venv：

```bash
cd /Users/eureka/Desktop/HyrusOCR
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[all]"
python -m pip install -r demo/requirements.txt
```

PaddlePaddle 的 CPU/GPU 安装方式与机器环境有关，请按项目
`docs/version3.x/installation.md` 安装。首次真实推理可能下载模型。

## 启动

从仓库根目录运行：

```bash
python -m uvicorn demo.app.main:app --host 127.0.0.1 --port 8000
```

打开：

- 页面：<http://127.0.0.1:8000>
- Swagger API：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/health>

### 快速 UI 演示

如果暂时没有安装模型或只想演示完整交互，可以开启 Mock 模式。文件识别和路由是真实执行的，仅跳过模型推理：

```bash
HYRUS_DEMO_MOCK=1 python -m uvicorn demo.app.main:app --host 127.0.0.1 --port 8000
```

其他环境变量：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `HYRUS_DEMO_DEVICE` | `cpu` | PaddleOCR 推理设备 |
| `HYRUS_DEMO_MAX_UPLOAD_MB` | `25` | 最大上传大小 |
| `HYRUS_DEMO_VL_BACKEND` | 空 | 如 `vllm-server` |
| `HYRUS_DEMO_VL_SERVER_URL` | 空 | VL 推理服务 URL |

## 通用 Demo 展示指令

以下指令适合本地演示，也适合后续迁移到服务器。核心思路是先用 Mock 模式确认页面、上传、路由和返回格式，再切到真实模型。

### 1. 本地快速演示

```bash
cd /Users/eureka/Desktop/HyrusOCR
conda activate hyrusocr
HYRUS_DEMO_MOCK=1 python -m uvicorn demo.app.main:app --host 127.0.0.1 --port 8000
```

浏览器打开：

- 页面：<http://127.0.0.1:8000>
- API 文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/health>

演示话术：

1. 上传 DOCX、XLSX、PPTX、PDF 或图片；
2. 选择 `auto` 路由；
3. 用 `hint` 模拟业务场景，例如 `document` 走版面结构解析，`scene` 走普通 OCR，`complex` 走 VL；
4. 查看页面右侧的路由决策、Markdown 输出和完整 JSON；
5. 强调当前 demo 已打通“输入 → 路由 → 解析器 → md/json 输出”的最小链路。

### 2. 本地真实模型演示

确认 PaddleOCR 和模型依赖安装完成后关闭 Mock：

```bash
cd /Users/eureka/Desktop/HyrusOCR
conda activate hyrusocr
python -m uvicorn demo.app.main:app --host 127.0.0.1 --port 8000
```

如果只验证路由、不跑模型，可以在页面勾选 Dry run，或调用：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/parse \
  -F "file=@tests/test_files/table.jpg" \
  -F "processor=auto" \
  -F "hint=document" \
  -F "dry_run=true"
```

### 3. 服务器展示

服务器上建议监听 `0.0.0.0`，再通过安全组、反向代理或内网访问控制暴露端口：

```bash
cd /path/to/HyrusOCR
conda activate hyrusocr
HYRUS_DEMO_MOCK=1 python -m uvicorn demo.app.main:app --host 0.0.0.0 --port 8000
```

访问地址替换为服务器 IP 或域名：

- 页面：`http://<server-host>:8000`
- API 文档：`http://<server-host>:8000/docs`
- 健康检查：`http://<server-host>:8000/health`

真实模型服务器启动：

```bash
cd /path/to/HyrusOCR
conda activate hyrusocr
HYRUS_DEMO_DEVICE=cpu python -m uvicorn demo.app.main:app --host 0.0.0.0 --port 8000
```

有 NVIDIA GPU 且 PaddlePaddle GPU 版安装正确时，可改为：

```bash
HYRUS_DEMO_DEVICE=gpu:0 python -m uvicorn demo.app.main:app --host 0.0.0.0 --port 8000
```

### 4. 接入 PaddleOCR-VL 服务

如果 VL 模型单独部署成推理服务，可以通过环境变量接入：

```bash
HYRUS_DEMO_VL_BACKEND=vllm-server \
HYRUS_DEMO_VL_SERVER_URL=http://127.0.0.1:8118/v1 \
python -m uvicorn demo.app.main:app --host 0.0.0.0 --port 8000
```

Apple Silicon 本地 VL 加速通常使用 `mlx-vlm-server`：

```bash
HYRUS_DEMO_VL_BACKEND=mlx-vlm-server \
HYRUS_DEMO_VL_SERVER_URL=http://127.0.0.1:8111/ \
python -m uvicorn demo.app.main:app --host 127.0.0.1 --port 8000
```

### 5. 生产化前需要补的内容

当前 demo 是同步请求服务，部署给多人使用前建议补齐：

1. 鉴权和上传限流；
2. 文件落盘到对象存储；
3. Redis/RabbitMQ 异步任务队列；
4. 任务状态查询接口；
5. 解析结果入库和全文索引；
6. 质量评分、失败重试和人工复核入口；
7. 结构化日志、模型耗时和路由命中率监控。

## API 示例

只验证路由：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/parse \
  -F "file=@tests/test_files/table.jpg" \
  -F "processor=auto" \
  -F "hint=document" \
  -F "dry_run=true"
```

执行真实解析：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/parse \
  -F "file=@tests/test_files/table.jpg" \
  -F "processor=auto" \
  -F "hint=document"
```

## 测试

路由单测只使用 Python 标准库：

```bash
PYTHONPATH=demo python -m unittest discover -s demo/tests -v
```
