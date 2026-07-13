# Models

Local GGUF model files for the in-process `llama-cpp-python` runtime live in
this directory. Model binaries (`*.gguf`, `*.bin`) are **gitignored** — they
are large and must never be committed.

## Default model

`scripts/download_model.ps1` (Windows) / `scripts/download_model.sh` (Unix)
fetches [Phi-3-mini-4k-instruct](https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf)
(Q4 quantization, ~2.3 GB) from Microsoft's official Hugging Face repository
and saves it as `models/model.gguf` — the `MODEL_PATH` default in
[.env.example](../.env.example).

Why this model:

- **License:** MIT — permissive, no gated access or account required.
- **Size:** 3.8B parameters at Q4 runs acceptably on CPU-only machines with
  ~4 GB of free RAM.
- **Quality:** a capable instruct-tuned model for its size, with a 4k context
  window matching the `LLM_CONTEXT_SIZE` default.

## Substituting another model

Any chat/instruct GGUF that `llama.cpp` supports works:

1. Download the `.gguf` file into this directory (or pass a URL to the
   download script: `scripts/download_model.sh <url>`).
2. Point `MODEL_PATH` in your `.env` at the file.
3. Adjust `LLM_CONTEXT_SIZE` to the model's context window and
   `LLM_GPU_LAYERS` if you built `llama-cpp-python` with GPU support (see
   [backend/README.md](../backend/README.md) for GPU build variants).
4. Restart the backend — the model loads once at startup, and startup fails
   with a clear error if the file is missing.

Check the license of any model you substitute; not all GGUF builds are
permissively licensed.
