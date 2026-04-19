import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { LLMManager } from './llmManager.js';
import { LlamaCppServer } from './llamaCppServer.js';
import { ConfigLoader } from './configLoader.js';
import { DoNoHarmManager } from '../utils/doNoHarmManager.js';
import Logger from '../utils/logging.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * Orchestrator - Main orchestration engine for LunaBlue
 * Manages the lifecycle of LLM models and the llama.cpp server
 */
export class Orchestrator {
  private llmManager: LLMManager;
  private llamaCppServer: LlamaCppServer;
  private configLoader: ConfigLoader;
  private doNoHarmManager: DoNoHarmManager;
  private logger = Logger.getLogger('Orchestrator');

  constructor() {
    this.configLoader = new ConfigLoader();
    this.llmManager = new LLMManager(this.configLoader);
    this.llamaCppServer = new LlamaCppServer(this.configLoader);
    this.doNoHarmManager = new DoNoHarmManager();
  }

  /**
   * Initialize the orchestrator
   * - Validate environment
   * - Load configurations
   * - Load DoNoHarm knowledge base
   * - Start default LLM
   */
  async initialize(): Promise<void> {
    try {
      this.logger.info('Initializing LunaBlue Orchestrator...');

      // Load configurations
      await this.configLoader.load();
      this.logger.info('Configuration loaded');

      // Load DoNoHarm knowledge base
      await this.doNoHarmManager.load();
      this.logger.info('DoNoHarm knowledge base loaded');

      // Get default model info
      const defaultModel = this.configLoader.getDefaultModel();
      this.logger.info(`Default model: ${defaultModel.name} (${defaultModel.id})`);

      // Start llama.cpp server with default model
      await this.llamaCppServer.start(defaultModel);
      this.logger.info('LLM server started');

      this.logger.info('LunaBlue Orchestrator initialized successfully');
    } catch (error) {
      this.logger.error(`Initialization failed: ${error}`);
      throw error;
    }
  }

  /**
   * Shutdown the orchestrator gracefully
   */
  async shutdown(): Promise<void> {
    this.logger.info('Shutting down LunaBlue Orchestrator...');
    try {
      await this.llamaCppServer.stop();
      this.logger.info('LunaBlue Orchestrator shutdown complete');
    } catch (error) {
      this.logger.error(`Shutdown error: ${error}`);
    }
  }

  /**
   * Get reference to LLM Manager
   */
  getLLMManager(): LLMManager {
    return this.llmManager;
  }

  /**
   * Get reference to llama.cpp Server
   */
  getLlamaCppServer(): LlamaCppServer {
    return this.llamaCppServer;
  }

  /**
   * Get reference to Config Loader
   */
  getConfigLoader(): ConfigLoader {
    return this.configLoader;
  }

  /**
   * Get reference to DoNoHarm Manager
   */
  getDoNoHarmManager(): DoNoHarmManager {
    return this.doNoHarmManager;
  }

  /**
   * Send prompt to active LLM and get response
   * Injects DoNoHarm context into the prompt
   */
  async prompt(text: string): Promise<string> {
    try {
      // Inject DoNoHarm context
      const contextualPrompt = this.doNoHarmManager.buildSystemPrompt(text);

      // Send to LLM
      const response = await this.llamaCppServer.sendPrompt(contextualPrompt);

      // Check compliance
      const compliance = this.doNoHarmManager.checkResponseCompliance(response);
      if (!compliance.compliant) {
        this.logger.warn(`Potential compliance issues: ${compliance.issues.join(', ')}`);
      }

      return response;
    } catch (error) {
      this.logger.error(`Prompt error: ${error}`);
      throw error;
    }
  }
}
