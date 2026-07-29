# HyrusOCR Demo: Linux ARM64 + NPU Deployment

This guide is for running the demo flow on a Linux ARM64 server with NPU:

```text
upload -> route -> parse -> markdown/json -> web display
```

The commands below assume Huawei Ascend NPU, because PaddleOCR provides a verified Ascend NPU path. If the NPU is not Ascend, replace the PaddlePaddle device package and device name according to the vendor runtime.

## Port Plan

Only ports `9001-9005` are assumed to be available.

| Port | Service | Required |
| --- | --- | --- |
| `9001` | HyrusOCR demo web UI and API | Yes |
| `9002` | Optional PaddleOCR-VL VLM service | Only for `hint=complex` / `processor=vl` |
| `9003` | Reserved for future OCR/Structure serving split | No |
| `9004` | Reserved for metrics/log viewer | No |
| `9005` | Reserved for reverse proxy or future gateway | No |

For the first runnable deployment, start only port `9001`.

## 1. Check Server

```bash
uname -m
npu-smi info
python3 --version
docker --version
```

Expected:

- `uname -m` is `aarch64` or `arm64`.
- `npu-smi info` can see the NPU card.
- Python is preferably `3.10` or `3.11`.

## 2. Pull Code

```bash
mkdir -p /data/apps
cd /data/apps
git clone https://github.com/Eureka-Zhang/HyrusOCR.git
cd HyrusOCR
```

If the repo already exists:

```bash
cd /data/apps/HyrusOCR
git pull origin main
```

## 3. Create Python Environment

Using conda:

```bash
conda create -n hyrusocr python=3.11 -y
conda activate hyrusocr
python -m pip install -U pip setuptools wheel
```

Using venv:

```bash
cd /data/apps/HyrusOCR
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip setuptools wheel
```

## 4. Install PaddlePaddle for Ascend NPU

For Ascend NPU, PaddleOCR docs recommend installing both the CPU package and the NPU custom package.

Stable package path:

```bash
python -m pip install paddlepaddle==3.2.0 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
python -m pip install paddle-custom-npu==3.2.0 -i https://www.paddlepaddle.org.cn/packages/stable/npu/
python -m pip install numpy==1.26.4 opencv-python==3.4.18.65
```

On ARM64, add this environment variable if `libgomp` reports a static TLS error:

```bash
export LD_PRELOAD=/usr/lib/aarch64-linux-gnu/libgomp.so.1:$LD_PRELOAD
```

Verify PaddlePaddle:

```bash
python -c "import paddle; paddle.utils.run_check()"
```

Expected output should include that PaddlePaddle works on NPU.

## 5. Install HyrusOCR Demo Dependencies

```bash
cd /data/apps/HyrusOCR
python -m pip install -e ".[all]"
python -m pip install -r demo/requirements.txt
```

## 6. Start Demo on Port 9001

Mock mode verifies upload, route, API response and UI without loading models:

```bash
cd /data/apps/HyrusOCR
HYRUS_DEMO_MOCK=1 \
HYRUS_DEMO_DEVICE=npu \
python -m uvicorn demo.app.main:app --host 0.0.0.0 --port 9001
```

Open:

```text
http://<server-host>:9001
```

Real NPU parsing:

```bash
cd /data/apps/HyrusOCR
HYRUS_DEMO_DEVICE=npu \
python -m uvicorn demo.app.main:app --host 0.0.0.0 --port 9001
```

If the runtime requires an explicit card index, use:

```bash
HYRUS_DEMO_DEVICE=npu:0 \
python -m uvicorn demo.app.main:app --host 0.0.0.0 --port 9001
```

## 7. Pull / Warm Model Weights

PaddleOCR normally downloads model weights during first real inference. To make the demo smoother, pre-warm with a sample request.

First start the real service on `9001`, then run:

```bash
curl -X POST http://127.0.0.1:9001/api/v1/parse \
  -F "file=@tests/test_files/table.jpg" \
  -F "processor=auto" \
  -F "hint=document"
```

This warms the `PP-StructureV3` path. To warm the plain OCR path:

```bash
curl -X POST http://127.0.0.1:9001/api/v1/parse \
  -F "file=@tests/test_files/table.jpg" \
  -F "processor=ocr" \
  -F "hint=scene"
```

After warm-up, refresh the web UI and upload a document/image again.

## 8. Optional: PaddleOCR-VL on Ascend NPU

Only use this if the demo must show `hint=complex` or `processor=vl`.

The official Ascend VL path is Docker-based. Start the VLM service on port `9002`:

```bash
docker run -it \
  --user root \
  --privileged \
  -v /usr/local/Ascend/driver:/usr/local/Ascend/driver \
  -v /usr/local/bin/npu-smi:/usr/local/bin/npu-smi \
  -v /usr/local/dcmi:/usr/local/dcmi \
  --shm-size 64g \
  --network host \
  ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/paddleocr-genai-vllm-server:latest-huawei-npu \
  paddleocr genai_server --model_name PaddleOCR-VL-1.6-0.9B --host 0.0.0.0 --port 9002 --backend vllm
```

Then start the demo with the VL backend configured:

```bash
HYRUS_DEMO_DEVICE=npu \
HYRUS_DEMO_VL_BACKEND=vllm-server \
HYRUS_DEMO_VL_SERVER_URL=http://127.0.0.1:9002/v1 \
python -m uvicorn demo.app.main:app --host 0.0.0.0 --port 9001
```

## 9. Keep the Service Running

For a quick server demo, use `nohup`:

```bash
cd /data/apps/HyrusOCR
nohup env HYRUS_DEMO_DEVICE=npu python -m uvicorn demo.app.main:app --host 0.0.0.0 --port 9001 > hyrusocr-demo.log 2>&1 &
```

Check:

```bash
curl http://127.0.0.1:9001/health
tail -f hyrusocr-demo.log
```

For a more stable deployment, use `systemd`, `supervisor`, or the platform process manager.

## 10. Verification Checklist

1. `curl http://127.0.0.1:9001/health` returns `ok`.
2. Browser can open `http://<server-host>:9001`.
3. Upload image + `hint=scene` routes to `ocr`.
4. Upload PDF or scanned document + `hint=document` routes to `structure`.
5. The response shows markdown and full JSON.
6. If VL is enabled, `hint=complex` routes to `vl` and returns a parsed result.

## Common Issues

| Symptom | What to check |
| --- | --- |
| Cannot import PaddlePaddle NPU | Confirm `paddlepaddle` and `paddle-custom-npu` versions match. |
| `npu-smi` not found in Docker | Mount `/usr/local/bin/npu-smi` and Ascend driver paths. |
| ARM64 `libgomp` error | Set `LD_PRELOAD=/usr/lib/aarch64-linux-gnu/libgomp.so.1:$LD_PRELOAD`. |
| First request is very slow | It is usually downloading and loading weights. Run warm-up once before the demo. |
| Port cannot be reached | Confirm firewall/security group allows `9001`, and uvicorn uses `--host 0.0.0.0`. |
| VL route fails | Start the VLM service on `9002` and set `HYRUS_DEMO_VL_BACKEND` / `HYRUS_DEMO_VL_SERVER_URL`. |
