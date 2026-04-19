# Configuration Guide

## Overview

LunaBlue uses JSON configuration files to manage models, settings, and behavior.

## Configuration Files

### 1. models.config.json

**Location**: `config/models.config.json`

Define available language models and llama.cpp server settings.

#### Example

```json
{
  "default_model": "phi-3-mini-4k-instruct",
  "models": [
    {
      "id": "phi-3-mini-4k-instruct",
      "name": "Phi-3 Mini (4K Context)",
      "type": "offline",
      "format": "gguf",
      "source": "huggingface",
      "repository": "microsoft/Phi-3-mini-4k-instruct-gguf",
      "filename": "Phi-3-mini-4k-instruct-q4.gguf",
      "url": "https://huggingface.co/.../Phi-3-mini-4k-instruct-q4.gguf",
      "local_path": "./models/phi-3-mini/",
      "context_window": 4096,
      "parameters": "3.8B",
      "quantization": "Q4_K_M",
      "active": true,
      "gpu_accelerated": true,
      "min_memory_gb": 4,
      "recommended_memory_gb": 8
    }
  ],
  "llama_cpp": {
    "port": 8000,
    "host": "127.0.0.1",
    "threads": "auto",
    "gpu_layers": "auto",
    "log_level": "info"
  },
  "donoharm": {
    "folder": "./DoNoHarm/",
    "enabled": true,
    "preload_on_startup": true
  }
}
```

#### Model Configuration Options

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique model identifier |
| `name` | string | Display name for UI |
| `type` | string | `offline` or `online` |
| `format` | string | Model format (e.g., `gguf`) |
| `repository` | string | HuggingFace repo ID |
| `filename` | string | Model file name |
| `local_path` | string | Local storage path |
| `context_window` | number | Max tokens |
| `parameters` | string | Model size (e.g., "3.8B") |
| `quantization` | string | Quantization type (e.g., "Q4_K_M") |
| `active` | boolean | Load this model on startup |
| `gpu_accelerated` | boolean | Support GPU offloading |
| `min_memory_gb` | number | Minimum RAM required |
| `recommended_memory_gb` | number | Recommended RAM |

#### llama.cpp Configuration Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `port` | number | 8000 | HTTP server port |
| `host` | string | 127.0.0.1 | Listen address |
| `threads` | string or number | "auto" | CPU threads (`auto` = system cores) |
| `gpu_layers` | string or number | "auto" | Layers to offload to GPU |
| `log_level` | string | "info" | Logging level |

#### DoNoHarm Configuration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `folder` | string | "./DoNoHarm/" | Path to knowledge base files |
| `enabled` | boolean | true | Enable knowledge base |
| `preload_on_startup` | boolean | true | Load files at startup |

### 2. app.config.json

**Location**: `config/app.config.json`

General application settings.

#### Example

```json
{
  "application": {
    "name": "LunaBlue",
    "version": "0.1.0",
    "environment": "development"
  },
  "server": {
    "port": 3000,
    "host": "localhost",
    "cors": {
      "enabled": true,
      "origin": "*"
    }
  },
  "logging": {
    "level": "info",
    "format": "json",
    "file": "logs/lunablue.log"
  },
  "paths": {
    "models": "./models",
    "config": "./config",
    "logs": "./logs",
    "temp": "./temp"
  },
  "startup": {
    "validate_environment": true,
    "auto_download_models": false,
    "start_default_model": true,
    "preload_donoharm": true
  }
}
```

#### Application Configuration Options

| Field | Type | Description |
|-------|------|-------------|
| `application.name` | string | Application name |
| `application.version` | string | Version string |
| `application.environment` | string | `development`, `production`, or `staging` |
| `server.port` | number | HTTP server port |
| `server.host` | string | Listen address |
| `server.cors.enabled` | boolean | Enable CORS |
| `server.cors.origin` | string | CORS origin (e.g., "*" or specific domain) |
| `logging.level` | string | Log level: `debug`, `info`, `warn`, `error` |
| `logging.format` | string | `json` or `text` |
| `logging.file` | string | Log file path |
| `startup.validate_environment` | boolean | Validate system on startup |
| `startup.start_default_model` | boolean | Auto-start default model |
| `startup.preload_donoharm` | boolean | Load knowledge base on startup |

## Customizing Configuration

### Adding a New Model

1. Add entry to `models` array in `models.config.json`:

```json
{
  "id": "llama-2-7b",
  "name": "Llama 2 (7B)",
  "repository": "TheBloke/Llama-2-7B-GGUF",
  "filename": "llama-2-7b.Q4_K_M.gguf",
  "local_path": "./models/llama-2-7b/",
  "context_window": 4096,
  "parameters": "7B",
  "quantization": "Q4_K_M",
  "active": false,
  "gpu_accelerated": true,
  "min_memory_gb": 6,
  "recommended_memory_gb": 12
}
```

2. Place model file at `./models/llama-2-7b/llama-2-7b.Q4_K_M.gguf`

3. Create metadata file `./models/llama-2-7b/model.metadata.json`

4. Restart LunaBlue to load the model

### Changing Default Model

Edit `models.config.json`:

```json
{
  "default_model": "llama-2-7b"
}
```

### Adjusting Resource Usage

For systems with limited memory, reduce `gpu_layers`:

```json
{
  "llama_cpp": {
    "gpu_layers": 20
  }
}
```

Lower values = more CPU-based inference, less GPU memory.

### Enabling Debug Logging

Set logging level in `app.config.json`:

```json
{
  "logging": {
    "level": "debug"
  }
}
```

## Environment-Specific Configuration

### Development

```json
{
  "application": {
    "environment": "development"
  },
  "logging": {
    "level": "debug"
  }
}
```

### Production

```json
{
  "application": {
    "environment": "production"
  },
  "logging": {
    "level": "warn"
  },
  "server": {
    "cors": {
      "enabled": false,
      "origin": "https://yourdomain.com"
    }
  }
}
```

## Configuration Validation

LunaBlue validates configurations on startup. Invalid configs will cause the application to fail with clear error messages.

## Backup & Version Control

Keep configuration backups:
- Commit stable configs to version control
- Use `.gitignore` to exclude sensitive configs
- Create config templates for common scenarios

## Troubleshooting

### "Configuration not found"
Check file paths in `config/` directory and ensure `.json` files are valid.

### "Invalid JSON in config"
Use a JSON validator: https://jsonlint.com/

### Model won't load
- Verify `active: true` in models list
- Check `local_path` points to model file
- Ensure `.gguf` file exists
