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
      version: '0.2.0',
      description: 'Multi-LLM Orchestration Layer with llama.cpp Integration',
      phase: 'Phase 2: llama.cpp + GPU + Web UI + DoNoHarm',
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
      },
      examples: {
        webUI: 'Visit http://localhost:3000/ui',
        health: 'curl http://localhost:3000/health',
        models: 'curl http://localhost:3000/api/models',
        doNoHarmStatus: 'curl http://localhost:3000/api/donoharm/status',
        prompt: 'curl -X POST http://localhost:3000/api/prompt -H "Content-Type: application/json" -d \'{"text":"Hello"}\'',
      },
      features: [
        'Full llama.cpp integration with process spawning',
        'Automatic GPU detection (NVIDIA/AMD/Metal)',
        'DoNoHarm ethical framework with context injection',
        'Interactive web UI with chat interface',
        'Multi-model support',
        'Streaming responses',
        'Conversation history'
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

  return app;
}
