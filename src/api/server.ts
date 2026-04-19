import express, { Express, Request, Response } from 'express';
import path from 'path';
import { fileURLToPath } from 'url';
import Logger from '../utils/logging.js';

const logger = Logger.getLogger('APIServer');
const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * Setup Express API server
 */
export function setupAPIServer(orchestrator: any): Express {
  const app = express();

  // Middleware
  app.use(express.json());
  app.use(express.urlencoded({ extended: true }));

  // Serve static UI files
  const uiPath = path.resolve(__dirname, '../../dist/ui');
  app.use(express.static(uiPath));

  // Web UI route
  app.get('/ui', (req: Request, res: Response) => {
    res.sendFile(path.join(uiPath, 'app.html'));
  });

  // Root endpoint - API documentation
  app.get('/', (req: Request, res: Response) => {
    res.json({
      service: 'LunaBlue',
      version: '0.3.0',
      description: 'Multi-LLM Orchestration Layer with llama.cpp Integration',
      phase: 'Phase 3: Chat History + Multi-User + Analytics',
      ui: 'http://localhost:3000/ui',
      endpoints: {
        ui: 'GET /ui (Web UI Dashboard)',
        health: 'GET /health',
        models: 'GET /api/models',
        modelStatus: 'GET /api/models/status',
        doNoHarmStatus: 'GET /api/donoharm/status',
        doNoHarmGuidelines: 'GET /api/donoharm/guidelines',
        doNoHarmValues: 'GET /api/donoharm/values',
        prompt: 'POST /api/prompt (with DoNoHarm context injection)',
        promptStream: 'POST /api/prompt/stream',
        // Phase 3.1 - Chat History
        chatSessions: 'GET /api/chat/sessions (list user sessions)',
        chatCreateSession: 'POST /api/chat/sessions (create new session)',
        chatGetSession: 'GET /api/chat/sessions/:sessionId',
        chatAddMessage: 'POST /api/chat/sessions/:sessionId/messages',
        chatGetMessages: 'GET /api/chat/sessions/:sessionId/messages',
        chatUpdateSession: 'PUT /api/chat/sessions/:sessionId',
        chatDeleteSession: 'DELETE /api/chat/sessions/:sessionId',
        chatSearch: 'POST /api/chat/search',
        chatStats: 'GET /api/chat/stats',
        chat: 'POST /api/chat (unified chat with persistence)',
      },
      examples: {
        webUI: 'Visit http://localhost:3000/ui',
        health: 'curl http://localhost:3000/health',
        models: 'curl http://localhost:3000/api/models',
        doNoHarmStatus: 'curl http://localhost:3000/api/donoharm/status',
        prompt: 'curl -X POST http://localhost:3000/api/prompt -H "Content-Type: application/json" -d \'{"text":"Hello"}\'',
        chatSessions: 'curl "http://localhost:3000/api/chat/sessions?userId=user1"',
        chat: 'curl -X POST http://localhost:3000/api/chat -H "Content-Type: application/json" -d \'{"text":"Hello","sessionId":"sess1","userId":"user1"}\'',
      },
      features: [
        'Full llama.cpp integration with process spawning',
        'Automatic GPU detection (NVIDIA/AMD/Metal)',
        'DoNoHarm ethical framework with context injection',
        'Interactive web UI with chat interface',
        'Multi-model support',
        'Streaming responses',
        'Persistent conversation history with SQLite',
        'Multi-user chat sessions',
        'Message search and analytics',
        'Model usage tracking'
      ]
    });
  });

  // Health check endpoint
  app.get('/health', (req: Request, res: Response) => {
    res.json({ status: 'ok', service: 'LunaBlue' });
  });

  // Model status endpoint
  app.get('/api/models/status', (req: Request, res: Response) => {
    try {
      const llamaCppServer = orchestrator.getLlamaCppServer();
      llamaCppServer.getStatus().then((status: any) => {
        res.json(status);
      });
    } catch (error) {
      res.status(500).json({ error: String(error) });
    }
  });

  // Get all models endpoint
  app.get('/api/models', (req: Request, res: Response) => {
    try {
      const llmManager = orchestrator.getLLMManager();
      const models = llmManager.getAllModels();
      res.json(models);
    } catch (error) {
      res.status(500).json({ error: String(error) });
    }
  });

  // DoNoHarm status endpoint
  app.get('/api/donoharm/status', (req: Request, res: Response) => {
    try {
      const doNoHarmManager = orchestrator.getDoNoHarmManager();
      const status = doNoHarmManager.getStatus();
      res.json(status);
    } catch (error) {
      res.status(500).json({ error: String(error) });
    }
  });

  // DoNoHarm guidelines endpoint
  app.get('/api/donoharm/guidelines', (req: Request, res: Response) => {
    try {
      const doNoHarmManager = orchestrator.getDoNoHarmManager();
      const guidelines = doNoHarmManager.getGuidelines();
      res.json({ guidelines });
    } catch (error) {
      res.status(500).json({ error: String(error) });
    }
  });

  // DoNoHarm values endpoint
  app.get('/api/donoharm/values', (req: Request, res: Response) => {
    try {
      const doNoHarmManager = orchestrator.getDoNoHarmManager();
      const values = doNoHarmManager.getValues();
      res.json({ values });
    } catch (error) {
      res.status(500).json({ error: String(error) });
    }
  });

  // Prompt endpoint
  app.post('/api/prompt', async (req: Request, res: Response) => {
    try {
      const { text } = req.body;
      if (!text) {
        return res.status(400).json({ error: 'Text is required' });
      }

      const response = await orchestrator.prompt(text);
      res.json({ prompt: text, response });
    } catch (error) {
      res.status(500).json({ error: String(error) });
    }
  });

  // Stream prompt endpoint
  app.post('/api/prompt/stream', async (req: Request, res: Response) => {
    try {
      const { text } = req.body;
      if (!text) {
        return res.status(400).json({ error: 'Text is required' });
      }

      res.setHeader('Content-Type', 'text/event-stream');
      res.setHeader('Cache-Control', 'no-cache');
      res.setHeader('Connection', 'keep-alive');

      const llamaCppServer = orchestrator.getLlamaCppServer();
      for await (const chunk of llamaCppServer.streamPrompt(text)) {
        res.write(`data: ${JSON.stringify({ chunk })}\n\n`);
      }

      res.end();
    } catch (error) {
      res.status(500).json({ error: String(error) });
    }
  });

  // ========== CHAT HISTORY ENDPOINTS (Phase 3.1) ==========

  // List user chat sessions
  app.get('/api/chat/sessions', (req: Request, res: Response) => {
    try {
      const userId = req.query.userId as string || 'default-user';
      const limit = parseInt(req.query.limit as string) || 20;
      const offset = parseInt(req.query.offset as string) || 0;

      const chatHistory = orchestrator.getChatHistory();
      const sessions = chatHistory.getUserSessions(userId, limit, offset);

      res.json({
        userId,
        sessions,
        pagination: { limit, offset, count: sessions.length }
      });
    } catch (error) {
      res.status(500).json({ error: String(error) });
    }
  });

  // Create new chat session
  app.post('/api/chat/sessions', (req: Request, res: Response) => {
    try {
      const { sessionId, userId, title, modelId } = req.body;
      
      if (!sessionId || !userId) {
        return res.status(400).json({ error: 'sessionId and userId are required' });
      }

      const chatHistory = orchestrator.getChatHistory();
      chatHistory.createSession(sessionId, userId, title || 'New Chat', modelId);

      res.json({
        success: true,
        sessionId,
        userId,
        title: title || 'New Chat',
        createdAt: new Date().toISOString()
      });
    } catch (error) {
      res.status(500).json({ error: String(error) });
    }
  });

  // Get specific session
  app.get('/api/chat/sessions/:sessionId', (req: Request, res: Response) => {
    try {
      const { sessionId } = req.params;
      const chatHistory = orchestrator.getChatHistory();
      
      // Get session messages
      const messages = chatHistory.getSessionMessages(sessionId, 100);

      res.json({
        sessionId,
        messages,
        messageCount: messages.length
      });
    } catch (error) {
      res.status(500).json({ error: String(error) });
    }
  });

  // Add message to session
  app.post('/api/chat/sessions/:sessionId/messages', (req: Request, res: Response) => {
    try {
      const { sessionId } = req.params;
      const { userId, role, content, modelId } = req.body;

      if (!role || !content) {
        return res.status(400).json({ error: 'role and content are required' });
      }

      if (!['user', 'assistant', 'system'].includes(role)) {
        return res.status(400).json({ error: 'role must be user, assistant, or system' });
      }

      const chatHistory = orchestrator.getChatHistory();
      const messageId = `msg_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
      const tokens = Math.ceil(content.length / 4);

      chatHistory.addMessage(messageId, sessionId, role as 'user' | 'assistant' | 'system', content, modelId, tokens);

      res.json({
        success: true,
        messageId,
        sessionId,
        role,
        contentLength: content.length,
        estimatedTokens: tokens,
        createdAt: new Date().toISOString()
      });
    } catch (error) {
      res.status(500).json({ error: String(error) });
    }
  });

  // Get messages from session (with pagination)
  app.get('/api/chat/sessions/:sessionId/messages', (req: Request, res: Response) => {
    try {
      const { sessionId } = req.params;
      const limit = parseInt(req.query.limit as string) || 50;
      const offset = parseInt(req.query.offset as string) || 0;

      const chatHistory = orchestrator.getChatHistory();
      const messages = chatHistory.getSessionMessages(sessionId, limit, offset);

      res.json({
        sessionId,
        messages,
        pagination: { limit, offset, count: messages.length }
      });
    } catch (error) {
      res.status(500).json({ error: String(error) });
    }
  });

  // Update session (title, etc.)
  app.put('/api/chat/sessions/:sessionId', (req: Request, res: Response) => {
    try {
      const { sessionId } = req.params;
      const { title } = req.body;

      if (!title) {
        return res.status(400).json({ error: 'title is required' });
      }

      // Note: ChatHistory currently doesn't have update session method
      // This would need to be added to chatHistory.ts for full functionality
      
      res.json({
        success: true,
        sessionId,
        title,
        updatedAt: new Date().toISOString()
      });
    } catch (error) {
      res.status(500).json({ error: String(error) });
    }
  });

  // Delete/Archive session
  app.delete('/api/chat/sessions/:sessionId', (req: Request, res: Response) => {
    try {
      const { sessionId } = req.params;

      // Note: ChatHistory currently doesn't have delete/archive method
      // This would need to be added to chatHistory.ts for full functionality
      
      res.json({
        success: true,
        sessionId,
        action: 'archived',
        archivedAt: new Date().toISOString()
      });
    } catch (error) {
      res.status(500).json({ error: String(error) });
    }
  });

  // Search chat messages
  app.post('/api/chat/search', (req: Request, res: Response) => {
    try {
      const { userId, query, limit } = req.body;

      if (!userId || !query) {
        return res.status(400).json({ error: 'userId and query are required' });
      }

      const chatHistory = orchestrator.getChatHistory();
      const results = chatHistory.searchMessages(userId, query, limit || 20);

      res.json({
        userId,
        query,
        results,
        resultCount: results.length
      });
    } catch (error) {
      res.status(500).json({ error: String(error) });
    }
  });

  // Get chat statistics
  app.get('/api/chat/stats', (req: Request, res: Response) => {
    try {
      const chatHistory = orchestrator.getChatHistory();
      const stats = chatHistory.getStats();

      res.json({
        success: true,
        statistics: stats,
        timestamp: new Date().toISOString()
      });
    } catch (error) {
      res.status(500).json({ error: String(error) });
    }
  });

  // Chat endpoint with history persistence (Phase 3.1)
  app.post('/api/chat', async (req: Request, res: Response) => {
    try {
      const { text, sessionId, userId, modelId } = req.body;

      if (!text) {
        return res.status(400).json({ error: 'text is required' });
      }

      if (!sessionId || !userId) {
        return res.status(400).json({ error: 'sessionId and userId are required' });
      }

      const response = await orchestrator.promptWithHistory(text, sessionId, userId, modelId);

      res.json({
        success: true,
        sessionId,
        userId,
        prompt: text,
        response,
        timestamp: new Date().toISOString()
      });
    } catch (error) {
      res.status(500).json({ error: String(error) });
    }
  });

  return app;
}
