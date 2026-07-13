# Models

Local GGUF model files for the in-process `llama-cpp-python` runtime live in
this directory.

- Model binaries (`*.gguf`, `*.bin`) are **gitignored** — they are large and
  must never be committed.
- Fetch a model with `scripts/download_model` (added in Step 7 of the
  [build plan](../docs/BuildPlan.md)), which downloads the GGUF file into this
  directory.
- Point the backend at the downloaded file via `MODEL_PATH` in your `.env`
  (see [.env.example](../.env.example)).
