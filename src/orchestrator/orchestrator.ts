import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { LLMManager } from './llmManager.js';
import { LlamaCppServer } from './llamaCppServer.js';
import { ConfigLoader } from './configLoader.js';
import { DoNoHarmManager } from '../utils/doNoHarmManager.js';
import { ChatHistory } from '../utils/chatHistory.js';
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
  private chatHistory: ChatHistory;
  private logger = Logger.getLogger('Orchestrator');

  constructor() {
    this.configLoader = new ConfigLoader();
    this.llmManager = new LLMManager(this.configLoader);
    this.llamaCppServer = new LlamaCppServer(this.configLoader);
    this.doNoHarmManager = new DoNoHarmManager();
    this.chatHistory = new ChatHistory();
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
   * Get reference to Chat History (SQLite-based persistence)
   */
  getChatHistory(): ChatHistory {
    return this.chatHistory;
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

  /**
   * Send prompt with session-based chat history persistence
   * Automatically saves user and assistant messages to database
   * 
   * @param text User message text
   * @param sessionId Chat session identifier
   * @param userId User identifier for multi-user support
   * @param modelId Model identifier to track usage
   * @returns LLM response text
   */
  async promptWithHistory(
    text: string,
    sessionId: string,
    userId: string,
    modelId?: string
  ): Promise<string> {
    try {
      const messageId = `msg_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
      
      // Estimate input tokens
      const inputTokens = Math.ceil(text.length / 4);
      
      // Save user message
      this.chatHistory.addMessage(messageId, sessionId, 'user', text, modelId, { input: inputTokens, output: 0 });
      this.logger.debug(`Saved user message to session ${sessionId}`);

      // Inject DoNoHarm context
      const contextualPrompt = this.doNoHarmManager.buildSystemPrompt(text);

      // Send to LLM
      const startTime = Date.now();
      const response = await this.llamaCppServer.sendPrompt(contextualPrompt);
      const durationMs = Date.now() - startTime;

      // Check compliance
      const compliance = this.doNoHarmManager.checkResponseCompliance(response);
      if (!compliance.compliant) {
        this.logger.warn(`Potential compliance issues: ${compliance.issues.join(', ')}`);
      }

      // Save assistant response
      const responseMessageId = `msg_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
      const outputTokens = Math.ceil(response.length / 4); // Rough estimate
      this.chatHistory.addMessage(responseMessageId, sessionId, 'assistant', response, modelId, { input: 0, output: outputTokens });
      this.logger.debug(`Saved assistant response to session ${sessionId}`);

      // Record model usage statistics
      if (modelId) {
        this.chatHistory.recordModelUsage(userId, modelId, durationMs, { input: inputTokens, output: outputTokens });
        this.logger.info(`Model usage recorded: ${modelId} - ${durationMs}ms, ${inputTokens + outputTokens} total tokens`);
      }

      return response;
    } catch (error) {
      this.logger.error(`Prompt with history error: ${error}`);
      throw error;
    }
  }
}
