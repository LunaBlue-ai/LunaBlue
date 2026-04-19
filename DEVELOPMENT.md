# LunaBlue Development Environment

A brief guide to getting started with LunaBlue development.

## Prerequisites

- Node.js 18+ (https://nodejs.org/)
- Python 3.9+ (https://www.python.org/)
- Git (https://git-scm.com/)

## Setup Steps

### 1. Install Node.js Dependencies
```bash
npm install
```

### 2. Install Python Dependencies (Optional)
```bash
pip install -r requirements.txt
```

### 3. Validate Environment
```bash
npm run validate
```

### 4. Install LunaBlue
```bash
npm run setup
```

### 5. Download Models
```bash
npm run setup:models
```

### 6. Build Project
```bash
npm run build
```

### 7. Start Development Server
```bash
npm run dev
```

## Useful Commands

- `npm run lint` - Check code style
- `npm test` - Run tests
- `npm run build` - Build TypeScript
- `npm start` - Run production build

## Project Structure Overview

- `src/` - TypeScript source code
  - `orchestrator/` - Core orchestration logic
  - `api/` - HTTP API server
  - `utils/` - Utility functions
- `config/` - Configuration files
- `models/` - GGUF model storage
- `DoNoHarm/` - Knowledge base
- `setup/` - Installation scripts
- `scripts/` - Utility scripts

## Key Technologies

- **TypeScript** - Primary language
- **Express.js** - HTTP API framework
- **Winston** - Logging
- **llama.cpp** - LLM inference engine
- **Axios** - HTTP client

## Next Steps

After setup, check out the main README for usage instructions and API documentation.
