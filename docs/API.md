# API Reference

## Base URL

```
http://localhost:3000
```

## Health Check

### GET /health

Check if the LunaBlue server is running.

**Response:**
```json
{
  "status": "ok",
  "service": "LunaBlue"
}
```

---

## Models

### GET /api/models

Get all available models.

**Response:**
```json
[
  {
    "id": "phi-3-mini-4k-instruct",
    "name": "Phi-3 Mini (4K Context)",
    "type": "offline",
    "format": "gguf",
    "context_window": 4096,
    "parameters": "3.8B",
    "quantization": "Q4_K_M",
    "active": true,
    "gpu_accelerated": true,
    "min_memory_gb": 4,
    "recommended_memory_gb": 8
  }
]
```

### GET /api/models/status

Get current model status and inference engine information.

**Response:**
```json
{
  "isRunning": true,
  "model": "phi-3-mini-4k-instruct",
  "uptime": 3600,
  "totalRequests": 42,
  "averageLatency": 250
}
```

---

## Text Completion

### POST /api/prompt

Get a single completion for a prompt.

**Request:**
```json
{
  "text": "What is artificial intelligence?"
}
```

**Response:**
```json
{
  "prompt": "What is artificial intelligence?",
  "response": "Artificial intelligence refers to computer systems designed to perform tasks that typically require human intelligence..."
}
```

**Status Codes:**
- `200` - Success
- `400` - Invalid request (missing `text` field)
- `500` - Server error

### POST /api/prompt/stream

Get streaming completion for a prompt (Server-Sent Events).

**Request:**
```json
{
  "text": "Write a poem about the moon"
}
```

**Response Headers:**
```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
```

**Response Stream:**
```
data: {"chunk":"The"}
data: {"chunk":" moon"}
data: {"chunk":" shines"}
data: {"chunk":" bright"}
...
```

---

## Error Handling

All endpoints return error responses in the following format:

```json
{
  "error": "Error message describing what went wrong"
}
```

### Common Errors

| Status | Error | Cause |
|--------|-------|-------|
| 400 | Missing required field | Incomplete request body |
| 500 | llama.cpp server is not running | Model not initialized |
| 500 | Model not found | Invalid model ID |
| 500 | Connection timeout | Network or llama.cpp issue |

---

## Client Libraries & Examples

### cURL

```bash
# Health check
curl http://localhost:3000/health

# Get models
curl http://localhost:3000/api/models

# Send prompt
curl -X POST http://localhost:3000/api/prompt \
  -H "Content-Type: application/json" \
  -d '{"text":"Hello, what is 2+2?"}'

# Stream prompt
curl -X POST http://localhost:3000/api/prompt/stream \
  -H "Content-Type: application/json" \
  -d '{"text":"Tell me a story"}' \
  --no-buffer
```

### JavaScript/TypeScript

```typescript
// Simple completion
const response = await fetch('http://localhost:3000/api/prompt', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ text: 'Hello!' })
});
const data = await response.json();
console.log(data.response);

// Streaming completion
const stream = await fetch('http://localhost:3000/api/prompt/stream', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ text: 'Tell me a story' })
});

const reader = stream.body?.getReader();
const decoder = new TextDecoder();

while (true) {
  const { done, value } = await reader!.read();
  if (done) break;
  
  const text = decoder.decode(value);
  const lines = text.split('\n');
  for (const line of lines) {
    if (line.startsWith('data: ')) {
      const data = JSON.parse(line.slice(6));
      process.stdout.write(data.chunk);
    }
  }
}
```

### Python

```python
import requests

# Simple completion
response = requests.post(
    'http://localhost:3000/api/prompt',
    json={'text': 'Hello!'}
)
print(response.json()['response'])

# Streaming completion
response = requests.post(
    'http://localhost:3000/api/prompt/stream',
    json={'text': 'Tell me a story'},
    stream=True
)

for line in response.iter_lines():
    if line.startswith(b'data: '):
        data = json.loads(line[6:])
        print(data['chunk'], end='', flush=True)
```

---

## Rate Limiting

Currently, no rate limiting is applied. In production, implement:
- Per-IP rate limiting
- Per-model token budget
- Queue management for concurrent requests

---

## Authentication

Currently, no authentication is required. For production deployment, implement:
- API keys
- Bearer token authentication
- JWT validation

---

## Versioning

API Version: `v1`

Future versions will maintain backward compatibility where possible.
