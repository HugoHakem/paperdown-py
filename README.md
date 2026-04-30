# paperdown-py

This is the streamlined local-first version of the workflow. It uses `uv` to build one Python environment containing:

- `glmocr` from the GLM-OCR SDK
- `glmocr[selfhosted]` dependencies, including `torch` and `torchvision` for local layout detection
- an Ollama config for `glm-ocr:latest`
- a vLLM/SGLang config for CUDA servers such as A100 nodes
- an optional Apple Silicon MLX config for `mlx-community/GLM-OCR-bf16`

The Python CLI calls `glmocr.GlmOcr` directly. There is no Rust wrapper, no SDK Flask server, and no subprocess call to the GLM-OCR CLI.

## Install

With direnv:

```bash
cd /Users/hakem/Projects/paperdown-py
direnv allow
```

The local `.envrc` unsets an empty `SOURCE_DATE_EPOCH`, runs `uv sync`, and activates `.venv`.

Without direnv:

```bash
cd /Users/hakem/Projects/paperdown-py
uv sync
source .venv/bin/activate
```

Check that the environment is local to this Python project:

```bash
python -c "import sys, torch, torchvision, glmocr; print(sys.executable); print(torch.__version__, torchvision.__version__)"
```

## Ollama Backend

Ollama is the default backend because it is more cross-platform. The GLM-OCR SDK recommends Ollama's native `/api/generate` endpoint, so the default config is:

```text
src/paperdown_py/configs/glmocr-local-ollama.yaml
```

First test Ollama from a normal Terminal:

```bash
ollama --version
ollama pull glm-ocr:latest
```

If the service is not already running:

```bash
ollama serve
```

In another terminal, verify the model responds:

```bash
curl http://localhost:11434/api/generate -d '{
  "model": "glm-ocr:latest",
  "prompt": "Hello",
  "stream": false
}'
```

Then convert. Since Ollama is the default config, no `--config` is needed:

```bash
paperdown-py convert \
  path/to/paper.pdf \
  --output md-ollama \
  --overwrite \
  --timeout 1800
```

If `ollama --version` crashes with an MLX/Metal stack trace, fix or reinstall Ollama first. In this Codex sandbox, the current `/usr/local/bin/ollama` crashes before printing a version, so Ollama must be tested from a normal macOS Terminal.

## vLLM / SGLang Backend

On a CUDA cluster, vLLM or SGLang is usually a better fit than Ollama. The conversion process still runs the GLM-OCR SDK locally for PDF loading, layout detection, cropping, and result assembly; vLLM serves only the GLM-OCR vision-language model over an OpenAI-compatible HTTP API.

Start vLLM on the GPU node:

```bash
vllm serve zai-org/GLM-OCR \
  --host 127.0.0.1 \
  --port 8080 \
  --served-model-name glm-ocr \
  --speculative-config '{"method": "mtp", "num_speculative_tokens": 3}'
```

Check the route before converting:

```bash
curl http://127.0.0.1:8080/v1/models
```

Then convert with the vLLM config:

```bash
paperdown-py convert path/to/paper.pdf \
  --config src/paperdown_py/configs/glmocr-local-vllm.yaml \
  --output md-vllm \
  --overwrite \
  --timeout 1800
```

The vLLM config uses:

```yaml
api_path: /v1/chat/completions
api_mode: openai
model: glm-ocr
```

A `404` usually means the config is pointed at the wrong backend route. Ollama native uses `http://127.0.0.1:11434/api/generate` with `api_mode: ollama_generate`; vLLM and SGLang use `http://127.0.0.1:8080/v1/chat/completions` with `api_mode: openai`.

## Legacy MLX Backend

The direct MLX backend is kept for Apple Silicon users who want it. Install the optional MLX extra:

```bash
uv sync --extra mlx
```

Start the MLX server in one terminal:

```bash
paperdown-py serve-mlx --port 8080
```

The first run downloads `mlx-community/GLM-OCR-bf16`.

In another terminal, convert with the MLX config:

```bash
paperdown-py convert \
  path/to/paper.pdf \
  --config src/paperdown_py/configs/glmocr-local-mlx.yaml \
  --output md-local \
  --overwrite \
  --timeout 1800
```

Disable image extraction:

```bash
paperdown-py convert path/to/paper.pdf \
  --output md-local \
  --overwrite \
  --timeout 1800 \
  --disable-image-extraction
```

The output folder contains `index.md`, the SDK JSON/Markdown files, `imgs/` when images are enabled, and `log.jsonl`.

## Optional Tmux Workflow

If you prefer one terminal window, use tmux directly:

```bash
cd /Users/hakem/Projects/paperdown-py
tmux new-session -s paperdown
```

In the first pane, start Ollama or MLX:

```bash
# Ollama, if not already running
ollama serve

# Or the legacy MLX backend
paperdown-py serve-mlx --port 8080
```

Create a second pane:

```bash
Ctrl-b %
```

In the second pane, run the conversion:

```bash
paperdown-py convert \
  path/to/paper.pdf \
  --output md-ollama \
  --overwrite \
  --timeout 1800
```

Detach with `Ctrl-b d`; reattach later with:

```bash
tmux attach -t paperdown
```
