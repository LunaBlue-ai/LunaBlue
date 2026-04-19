# LunaBlue - Multi-LLM Orchestration Framework

A cross-platform, offline-first AI orchestration layer with embedded language model capabilities. LunaBlue provides a lightweight, always-available default model (Phi-3 Mini) running locally via llama.cpp, with support for multi-model switching and knowledge base context injection.

## 🌙 Features

- **Offline-First**: All models run locally with zero internet requirement after setup
- **Multi-LLM Support**: Easy model switching via configuration
- **GPU Acceleration**: Automatic CUDA, Metal, and Vulkan GPU detection and utilization
- **Lightweight**: Optimized for small commercial hardware (4GB RAM minimum)
- **Always-On Model**: LunaBlueAI remains running for instant responses
- **Knowledge Base Integration**: DoNoHarm markdown files loaded into context at startup
- **Cross-Platform**: Linux, Windows, macOS support
- **REST API**: Simple HTTP interface for prompts and model management
- **TypeScript/Python**: Type-safe orchestration with Python utilities

## 📋 Requirements

### Minimum
- **RAM**: 4GB (8GB recommended)
- **Disk**: 8GB free (for models and cache)
- **OS**: Windows 10+, macOS 10.15+, Linux (Ubuntu 18.04+)
- **CPU**: 2+ cores (performance improves with more cores)

### Optional
- **GPU**: NVIDIA (CUDA 11.8+), Apple Silicon (Metal), AMD (Vulkan)

## 🚀 Quick Start

### 1. Installation

```bash
# Clone the repository
git clone <repo-url>
cd LunaBlue

# Install Node.js dependencies
npm install

# Run installation setup
npm run setup
```

### 2. Download Models

```bash
# Download default model (Phi-3 Mini) from HuggingFace
npm run setup:models
```

This will download the quantized GGUF model (~2GB). You can manually place models in the `models/` directory if preferred.

### 3. Start LunaBlue

```bash
# Build TypeScript
npm run build

# Start the server
npm run start
```

The application will:
- Load configuration from `config/`
- Load DoNoHarm knowledge base from `DoNoHarm/`
- Start llama.cpp server with the default model
- Launch the HTTP API on `http://localhost:3000`

### 4. Use the Application

#### Command Line Test
```bash
# Send a prompt
curl -X POST http://localhost:3000/api/prompt \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello, how are you?"}'
```

#### Web UI
Open the web UI (during Phase 2) to interact with LunaBlueAI

## 📁 Project Structure

```
LunaBlue/
├── src/
│   ├── orchestrator/          # Core orchestration engine
│   │   ├── orchestrator.ts    # Main orchestrator
│   │   ├── llmManager.ts      # Model lifecycle management
│   │   ├── llamaCppServer.ts  # llama.cpp wrapper
│   │   └── configLoader.ts    # Configuration management
│   ├── api/                   # REST API server
│   │   └── server.ts          # Express.js setup
│   ├── ui/                    # Frontend (Phase 2)
│   └── utils/                 # Utilities
│       ├── logging.ts         # Winston logger
│       ├── environment.ts     # Environment validation
│       └── modelDownloader.ts # HuggingFace downloader
├── models/                    # GGUF models storage
│   └── phi-3-mini/           # Default model
├── DoNoHarm/                  # Knowledge base
│   ├── guidelines.md         # Usage guidelines
│   ├── values.md             # Core values
│   └── README.md             # Instructions
├── config/                    # Configuration files
│   ├── models.config.json    # Model registry
│   └── app.config.json       # App settings
├── setup/                     # Installation scripts
│   ├── install.ts            # Main installer
│   ├── setupModels.ts        # Model downloader
│   └── validateEnvironment.ts # Environment check
├── scripts/                   # Utility scripts
│   ├── download-models.py    # Batch downloader
│   └── generate-metadata.py  # Metadata generator
└── package.json              # Node.js config
```

## ⚙️ Configuration

### models.config.json

Define available models and llama.cpp settings:

```json
{
  "default_model": "phi-3-mini-4k-instruct",
  "models": [
    {
      "id": "phi-3-mini-4k-instruct",
      "name": "Phi-3 Mini",
      "active": true,
      "gpu_accelerated": true
    }
  ],
  "llama_cpp": {
    "port": 8000,
    "threads": "auto",
    "gpu_layers": "auto"
  }
}
```

### app.config.json

General application settings:

```json
{
  "application": {
    "name": "LunaBlue",
    "environment": "development"
  },
  "server": {
    "port": 3000,
    "host": "localhost"
  },
  "startup": {
    "start_default_model": true,
    "preload_donoharm": true
  }
}
```

## 📚 API Endpoints

### Health Check
```bash
GET /health
```

### Get All Models
```bash
GET /api/models
```

### Model Status
```bash
GET /api/models/status
```

### Send Prompt (Simple)
```bash
POST /api/prompt
Content-Type: application/json

{
  "text": "Your prompt here"
}
```

Response:
```json
{
  "prompt": "Your prompt here",
  "response": "LLM response text"
}
```

### Stream Prompt (Real-time)
```bash
POST /api/prompt/stream
Content-Type: application/json

{
  "text": "Your prompt here"
}
```

Returns Server-Sent Events (SSE) stream of response chunks.

### Chat with Persistent History (Phase 3.1)

#### Create Session
```bash
POST /api/chat/sessions
Content-Type: application/json

{
  "sessionId": "sess-123",
  "userId": "user-456",
  "title": "My Chat Session",
  "modelId": "phi-3-mini-4k-instruct"
}
```

#### Send Message with Auto-Save
```bash
POST /api/chat
Content-Type: application/json

{
  "text": "What is machine learning?",
  "sessionId": "sess-123",
  "userId": "user-456",
  "modelId": "phi-3-mini-4k-instruct"
}
```

Response:
```json
{
  "success": true,
  "sessionId": "sess-123",
  "userId": "user-456",
  "prompt": "What is machine learning?",
  "response": "Machine learning is a subset of AI...",
  "timestamp": "2024-01-15T10:30:00.000Z"
}
```

#### Get Session History
```bash
GET /api/chat/sessions/sess-123/messages?limit=50&offset=0
```

#### Search Conversations
```bash
POST /api/chat/search
Content-Type: application/json

{
  "userId": "user-456",
  "query": "machine learning",
  "limit": 20
}
```

#### View Chat Statistics
```bash
GET /api/chat/stats
```

Returns database statistics including total sessions, messages, and users.

## 🧠 DoNoHarm Knowledge Base

The `DoNoHarm/` folder contains markdown files that are loaded into LunaBlueAI's context at startup:

- **guidelines.md**: Usage guidelines and content policies
- **values.md**: Core principles and values
- Add custom `.md` files to extend the knowledge base

Example addition:
```markdown
# Custom Policy

LunaBlueAI should always:
- Provide accurate information
- Decline harmful requests
- Respect user privacy
```

## 🛠️ Development

### Build
```bash
npm run build
```

### Development Mode
```bash
npm run dev
```

### Linting
```bash
npm run lint
```

### Testing
```bash
npm test
```

## 📦 Installing Dependencies

### Node.js Dependencies
```bash
npm install
```

### Python Dependencies (optional, for scripts)
```bash
pip install -r requirements.txt
```

## 🤝 Adding New Models

1. Add model configuration to `config/models.config.json`
2. Ensure model is in GGUF format in `models/[model-name]/` directory
3. Create metadata file: `models/[model-name]/model.metadata.json`
4. Restart LunaBlue to load the new model

Example:
```json
{
  "id": "llama-2-7b",
  "name": "Llama 2 (7B)",
  "repository": "TheBloke/Llama-2-7B-GGUF",
  "filename": "llama-2-7b.Q4_K_M.gguf",
  "local_path": "./models/llama-2-7b/",
  "active": false
}
```

## 🚨 Troubleshooting

### Model won't start
1. Verify model file exists in correct directory
2. Check memory availability: `free -h` (Linux) or Task Manager (Windows)
3. Review logs: `tail logs/lunablue.log`

### GPU not detected
1. Verify GPU drivers are installed
2. Check GPU support: NVIDIA CUDA, Apple Metal, or AMD Vulkan
3. Review configuration: `config/models.config.json`

### API not responding
1. Check if server is running: `http://localhost:3000/health`
2. Review logs for errors
3. Verify network configuration and firewall settings

## 📖 Documentation

- [Setup Guide](./docs/SETUP.md) - Detailed installation instructions
- [API Documentation](./docs/API.md) - Complete API reference
- [Configuration Guide](./docs/CONFIG.md) - Configuration options

## 📄 License

MIT License - see LICENSE file

## 🎯 Roadmap

### Phase 1 ✅ Complete
- ✅ Core orchestrator
- ✅ llama.cpp integration
- ✅ REST API
- ✅ Configuration system
- ✅ Model management

### Phase 2 ✅ Complete
- ✅ Web UI with text input/output
- ✅ Multi-model switching infrastructure
- ✅ DoNoHarm context injection 
- ✅ GPU acceleration detection
- ✅ Performance monitoring
- ✅ Streaming responses

### Phase 3 - Advanced Features (In Progress)

#### Phase 3.1 ✅ Complete - Chat History & Persistence
- ✅ SQLite-based persistent chat storage
- ✅ Multi-user session management
- ✅ Message history with role tracking (user/assistant)
- ✅ Model usage analytics and statistics
- ✅ Full-text search across conversations
- ✅ 10+ REST API endpoints for chat operations
- ✅ Automatic token tracking and estimation
- ✅ Session archiving and management

#### Phase 3.2 - Model Hot-Swapping (Next)
- Model lifecycle management without server restart
- Graceful model switching
- State preservation across model changes
- Memory management optimization

#### Phase 3.3 - Fine-tuning Framework
- LoRA adapter support
- Instruction fine-tuning interface
- Dataset management
- Training progress monitoring

#### Phase 3.4 - Model Marketplace
- Discover and install community models
- Model ratings and reviews
- Version management
- License handling

#### Phase 3.5 - Advanced Analytics
- Usage tracking per user/model
- Performance metrics and insights
- Response quality evaluation
- Cost estimation and optimization

## 🧠 Chat History Database

LunaBlue uses SQLite with Write-Ahead Logging (WAL) for persistent, concurrent chat history storage. The database is automatically created at `data/lunablue.db` on first startup.

### Database Schema

**Sessions Table**
```sql
CREATE TABLE sessions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  title TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  model_id TEXT,
  system_prompt TEXT,
  metadata TEXT,
  archived BOOLEAN DEFAULT 0
);
```

**Messages Table**
```sql
CREATE TABLE messages (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  role TEXT NOT NULL,  -- 'user', 'assistant', or 'system'
  content TEXT NOT NULL,
  model_id TEXT,
  tokens_input INTEGER,
  tokens_output INTEGER,
  created_at INTEGER NOT NULL,
  FOREIGN KEY (session_id) REFERENCES sessions(id)
);
```

**Model Usage Table**
```sql
CREATE TABLE model_usage (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  model_id TEXT NOT NULL,
  prompt_count INTEGER,
  total_tokens_input INTEGER,
  total_tokens_output INTEGER,
  total_duration_ms INTEGER,
  last_used INTEGER NOT NULL,
  created_at INTEGER NOT NULL
);
```

### Automatic Features

- **Token Tracking**: Input and output tokens tracked separately for each message
- **Usage Statistics**: Model performance metrics recorded per user and model
- **Concurrent Access**: WAL mode enables safe concurrent read/write operations
- **Automatic Indexing**: Indexes created on frequently queried columns for performance
- **Cascading Deletes**: Deleting a session automatically removes all associated messages

### Accessing Chat History

#### Programmatic Access (TypeScript)
```typescript
import { ChatHistory } from './src/utils/chatHistory';

const history = new ChatHistory();

// Create session
history.createSession('sess-1', 'user-1', 'My Chat');

// Add message
history.addMessage('msg-1', 'sess-1', 'user', 'Hello!', 'phi-3-mini', 
  { input: 2, output: 0 });

// Get messages
const messages = history.getSessionMessages('sess-1', 50);

// Search
const results = history.searchMessages('user-1', 'keyword', 20);

// Get statistics
const stats = history.getStats();
```

#### REST API Access
See "Chat with Persistent History" section under API Endpoints above.

### Database Location

The chat history database is stored at:
- **Default**: `{project-root}/data/lunablue.db`
- **Custom**: Pass custom path to `ChatHistory` constructor

The `data/` directory is created automatically if it doesn't exist.

## 🤝 Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Submit a pull request

## 📞 Support

For issues and questions:
- GitHub Issues: [Create an issue](../../issues)
- Documentation: See `docs/` folder

---

**LunaBlue** - Always thinking, always available. 🌙