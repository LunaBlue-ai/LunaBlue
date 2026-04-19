"""
Quick reference for common development tasks in LunaBlue
"""

# Build & Run

npm install              # Install dependencies
npm run validate        # Check environment
npm run setup          # Initialize application  
npm run build          # Compile TypeScript
npm run dev            # Development mode (watch)
npm start              # Production mode

# Setup & Deployment

npm run setup:models   # Download models from HuggingFace
python setup/setup_environment.py  # Validate system

# Code Quality

npm run lint           # Check code style
npm test              # Run tests

# Python Utilities

python scripts/download-models.py          # Batch model downloader
python scripts/generate-metadata.py        # Auto-generate metadata
python setup/setup_environment.py          # Environment validation

# Testing API

# Health check
curl http://localhost:3000/health

# Get models
curl http://localhost:3000/api/models

# Send prompt
curl -X POST http://localhost:3000/api/prompt \
  -H "Content-Type: application/json" \
  -d '{"text":"Hello, how are you?"}'

# Stream prompt
curl -X POST http://localhost:3000/api/prompt/stream \
  -H "Content-Type: application/json" \
  -d '{"text":"Tell me a story"}' \
  --no-buffer

# Project Structure

src/                   # TypeScript source
  orchestrator/        # Core orchestration
    orchestrator.ts    # Main orchestrator
    llmManager.ts      # Model management
    llamaCppServer.ts  # Inference server
    configLoader.ts    # Configuration
  api/
    server.ts          # REST API
  ui/
    index.html         # Web UI (Phase 2)
  utils/               # Utilities
    logging.ts         # Winston logger
    environment.ts     # Environment checks
    modelDownloader.ts # HuggingFace download

config/                # Configuration files
  models.config.json   # Model registry
  app.config.json      # App settings

models/                # GGUF models storage
  phi-3-mini/         # Default model
    model.gguf
    model.metadata.json

DoNoHarm/              # Knowledge base
  guidelines.md        # Usage guidelines
  values.md            # Core values

setup/                 # Installation
  install.ts           # Main installer
  setupModels.ts       # Model setup
  validateEnvironment.ts

scripts/               # Utilities
  download-models.py   # Batch downloader
  generate-metadata.py # Metadata generator

docs/                  # Documentation
  SETUP.md            # Installation guide
  API.md              # API reference
  ARCHITECTURE.md     # System design
  CONFIG.md           # Configuration guide

package.json          # Node.js config
tsconfig.json         # TypeScript config
README.md             # Project README

# Key Concepts

Orchestrator
  ├── LLMManager (model selection & metadata)
  ├── LlamaCppServer (inference)
  └── ConfigLoader (configuration)

DoNoHarm
  └── Knowledge base (markdown files)
      └── Loaded at startup
          └── Available in context

REST API
  ├── /health (status)
  ├── /api/models (model list)
  ├── /api/prompt (simple completion)
  └── /api/prompt/stream (streaming)

# Debugging Tips

# Check if server is running
curl http://localhost:3000/health

# View logs (real-time)
tail -f logs/lunablue.log

# Check model status
curl http://localhost:3000/api/models/status

# Verify environment
npm run validate

# Test in development mode with increased logging
LOG_LEVEL=debug npm run dev
"""
