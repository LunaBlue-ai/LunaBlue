# Setup Guide

Complete step-by-step guide for installing and running LunaBlue.

## Prerequisites

### System Requirements
- **OS**: Windows 10+, macOS 10.15+, or Linux (Ubuntu 18.04+)
- **CPU**: 2+ cores recommended
- **RAM**: 4GB minimum, 8GB recommended
- **Disk**: 8GB free space

### Software Requirements
- Node.js 18.0.0 or higher
- Python 3.9 or higher (optional, for utility scripts)
- Git (optional, for cloning repository)

## Installation Steps

### Step 1: Clone or Initialize Project

If starting fresh:
```bash
mkdir LunaBlue
cd LunaBlue
git init
```

Or clone existing repository:
```bash
git clone <repository-url>
cd LunaBlue
```

### Step 2: Install Dependencies

```bash
# Install Node.js dependencies
npm install

# (Optional) Install Python dependencies
pip install -r requirements.txt
```

### Step 3: Validate Environment

```bash
# Run environment validation
npm run validate

# Or using Python
python setup/setup_environment.py
```

This checks:
- OS compatibility
- Required software versions
- Disk space availability
- Write permissions

### Step 4: Initialize Application

```bash
# Run setup script
npm run setup
```

This will:
- Create necessary directories
- Load configuration files
- Initialize DoNoHarm knowledge base
- Set up logging

### Step 5: Download Models

```bash
# Download default model from HuggingFace
npm run setup:models

# Or manually use Python script
python scripts/download-models.py --config config/models.config.json
```

**Note**: This downloads ~2GB. The model will be cached locally and requires internet only for this initial download.

### Step 6: Build Project

```bash
# Compile TypeScript to JavaScript
npm run build
```

### Step 7: Start LunaBlue

```bash
# Start the application
npm start
```

You should see:
```
================================================
LunaBlueAI Orchestration Layer
Version 0.1.0
================================================
LunaBlue API server running on http://localhost:3000
```

## Verification

### Check Server Health

Open terminal and run:
```bash
curl http://localhost:3000/health
```

Expected response:
```json
{"status":"ok","service":"LunaBlue"}
```

### List Available Models

```bash
curl http://localhost:3000/api/models
```

### Send Test Prompt

```bash
curl -X POST http://localhost:3000/api/prompt \
  -H "Content-Type: application/json" \
  -d '{"text":"Hello, what is your name?"}'
```

## Development Setup

For development with auto-reload:

```bash
# Install TypeScript globally (optional)
npm install -g ts-node

# Run in development mode
npm run dev
```

This enables hot-reload when files change.

## Configuration Guide

### models.config.json

Located in `config/models.config.json`:

```json
{
  "default_model": "phi-3-mini-4k-instruct",
  "models": [
    {
      "id": "model-id",
      "name": "Display Name",
      "repository": "huggingface/repo",
      "filename": "model.gguf",
      "local_path": "./models/model-name/",
      "active": true
    }
  ],
  "llama_cpp": {
    "port": 8000,
    "threads": "auto",
    "gpu_layers": "auto"
  }
}
```

Key settings:
- `default_model`: Model ID to use at startup
- `models[].active`: Set to `false` to skip loading
- `llama_cpp.port`: Change if 8000 is occupied
- `llama_cpp.threads`: Set to specific number or "auto"
- `llama_cpp.gpu_layers`: Set layers to offload to GPU

### app.config.json

Located in `config/app.config.json`:

```json
{
  "server": {
    "port": 3000,
    "host": "localhost"
  },
  "logging": {
    "level": "info"
  },
  "startup": {
    "start_default_model": true,
    "preload_donoharm": true
  }
}
```

## Customizing DoNoHarm Knowledge Base

Add custom guidelines to `DoNoHarm/` folder:

1. Create new markdown file: `DoNoHarm/custom-guidelines.md`
2. Add your content:
```markdown
# Custom Guidelines

[Your guidelines content]
```
3. Restart LunaBlue to load changes

## Troubleshooting

### "Node.js not found"
Install from https://nodejs.org/

Check installation:
```bash
node --version
npm --version
```

### "Port 3000 already in use"
Change server port in `config/app.config.json`:
```json
{
  "server": {
    "port": 3001
  }
}
```

### "Not enough disk space"
Ensure at least 8GB free space for models and cache:

```bash
# Linux/macOS
df -h

# Windows
wmic logicaldisk get name, size, freespace
```

### "Model download fails"
Manually download from [HuggingFace Phi-3-Mini](https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf) and place in:
```
models/phi-3-mini/Phi-3-mini-4k-instruct-q4.gguf
```

### "API returns 500 error"
Check logs:
```bash
tail -f logs/lunablue.log
```

### "High memory usage"
Reduce `gpu_layers` in `config/models.config.json` to offload less to GPU and use more CPU.

## Uninstallation

To remove LunaBlue:

```bash
# Delete models to free disk space
rm -rf models/

# Remove dependencies
rm -rf node_modules/

# Clear Python dependencies (if installed)
pip uninstall -r requirements.txt -y

# Delete project directory
rm -rf LunaBlue/
```

## Next Steps

1. Read [API Documentation](./API.md) for available endpoints
2. Check [Architecture Overview](./ARCHITECTURE.md) for system design
3. Review [DEVELOPMENT.md](../DEVELOPMENT.md) for development workflow
