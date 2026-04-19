# LunaBlue Model Metadata Template

This directory contains GGUF models and their metadata files.

## File Structure

Each model should have:
- `model.gguf` - The actual GGUF model file
- `model.metadata.json` - ModelMetadata describing the model

## Adding a Model

1. Place the `.gguf` file in this directory
2. Create a `model.metadata.json` file using the template below
3. Update `config/models.config.json` to reference the model

## Metadata Template Example

```json
{
  "metadata": {
    "model_id": "phi-3-mini-4k-instruct",
    "name": "Phi-3 Mini (4K Context)",
    "description": "3.8B parameter quantized model optimized for small hardware",
    "version": "1.0.0",
    "release_date": "2024-04-18"
  },
  "specifications": {
    "parameters": "3.8B",
    "context_window": 4096,
    "architecture": "Transformer",
    "quantization": "Q4_K_M",
    "quantization_bits": 4,
    "file_size_gb": 2.0,
    "format": "GGUF"
  },
  "performance": {
    "min_memory_gb": 4,
    "recommended_memory_gb": 8,
    "tokens_per_second_cpu": 10,
    "tokens_per_second_gpu": 50,
    "latency_ms_cpu": 100,
    "latency_ms_gpu": 20
  },
  "source": {
    "organization": "Microsoft",
    "repository_url": "https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf",
    "license": "MIT"
  }
}
```
