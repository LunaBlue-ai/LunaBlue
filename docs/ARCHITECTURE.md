# Architecture Overview

## System Design

LunaBlue is built on a layered architecture that separates concerns and enables scalability:

### Layer 1: Orchestration Layer
- **File**: `src/orchestrator/orchestrator.ts`
- **Purpose**: Manages the lifecycle of the entire system
- **Responsibilities**:
  - Initialize and shutdown components
  - Manage model lifecycle
  - Coordinate between API and inference engine

### Layer 2: Model Management
- **File**: `src/orchestrator/llmManager.ts`
- **Purpose**: Handle model selection, validation, and metadata
- **Responsibilities**:
  - Track available models
  - Validate model integrity
  - Switch between models
  - Report performance metrics

### Layer 3: LLM Inference
- **File**: `src/orchestrator/llamaCppServer.ts`
- **Purpose**: Interface with llama.cpp for model inference
- **Responsibilities**:
  - Spawn and manage llama.cpp process
  - Handle HTTP communication to llama.cpp API
  - Stream responses
  - Monitor server health

### Layer 4: Configuration
- **File**: `src/orchestrator/configLoader.ts`
- **Purpose**: Handle all configuration management
- **Responsibilities**:
  - Load JSON configuration files
  - Validate configuration
  - Provide configuration to other components

### Layer 5: HTTP API
- **File**: `src/api/server.ts`
- **Purpose**: Expose orchestration layer via REST API
- **Endpoints**:
  - `/health` - Server health
  - `/api/models` - List models
  - `/api/prompt` - Send prompt (simple)
  - `/api/prompt/stream` - Send prompt (streaming)

## Data Flow

```
User Input
    ↓
HTTP API (Express)
    ↓
Orchestrator
    ↓
LLM Manager → Config Loader
    ↓
llama.cpp Server (inferencing)
    ↓
Response → HTTP API
    ↓
User Output
```

## Configuration Management

```
config/
├── models.config.json        (Model registry & llama.cpp settings)
├── app.config.json          (Application settings)
└── [loading via ConfigLoader]
```

## Runtime Dependencies

- **llama.cpp**: Inference engine (external process)
- **Express.js**: HTTP server
- **Axios**: HTTP client (for llama.cpp communication)
- **Winston**: Logging

## Scaling Considerations

### Multi-Model Support
- Models listed in configuration
- Easy switching via model ID
- No restart required (planned Phase 2)

### GPU Acceleration
- Detected at startup
- Configured in models.config.json
- Auto-fallback to CPU

### Resource Management
- Memory-efficient GGUF quantization
- Model preloading in DoNoHarm
- Streaming responses for memory efficiency

## Knowledge Base Integration (DoNoHarm)

The `DoNoHarm/` knowledge base is loaded at startup and maintained in memory:

```
LunaBlueAI Initialization
    ↓
Load DoNoHarm/*.md files
    ↓
Inject into context
    ↓
Ready for prompts
```

This ensures consistent, values-aligned responses throughout the session.
