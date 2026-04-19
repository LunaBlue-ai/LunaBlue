import axios from 'axios';
import Logger from '../utils/logging.js';
import { ProcessManager } from '../utils/processManager.js';
import { GPUDetector } from '../utils/gpuDetector.js';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * LlamaCppServer - Wrapper around llama.cpp process
 * Manages model loading and inference via HTTP API
 */
export class LlamaCppServer {
  private processManager: ProcessManager | null = null;
  private baseUrl: string = '';
  private port: number = 8000;
  private logger = Logger.getLogger('LlamaCppServer');
  private configLoader: any;
  private isRunning = false;
  private isMockMode = false;
  private healthCheckRetries = 0;
  private maxHealthRetries = 12; // 12 retries * 5 seconds = 60 seconds timeout

  constructor(configLoader: any) {
    this.configLoader = configLoader;
    // Configuration will be loaded during start()
  }

  /**
   * Initialize server configuration (must be called after config is loaded)
   */
  private initializeConfig(): void {
    if (!this.baseUrl) {
      const modelsConfig = this.configLoader.getModelsConfig();
      // Use llama_cpp port from config, default to 8000
      const llamaCppConfig = modelsConfig.llama_cpp || {};
      this.port = llamaCppConfig.port || 8000;
      this.baseUrl = `http://127.0.0.1:${this.port}`;
    }
  }

  /**
   * Wait for server to be healthy with retries
   */
  private async waitForServerReady(): Promise<void> {
    // Skip health checks if in mock mode
    if (this.processManager?.isMockModeEnabled()) {
      this.logger.info('Mock mode enabled, skipping health checks');
      return;
    }

    this.healthCheckRetries = 0;
    while (this.healthCheckRetries < this.maxHealthRetries) {
      try {
        const response = await axios.get(`${this.baseUrl}/health`, { timeout: 2000 });
        if (response.status === 200) {
          this.logger.info('llama.cpp server is ready');
          return;
        }
      } catch {
        this.healthCheckRetries++;
        this.logger.debug(`Health check ${this.healthCheckRetries}/${this.maxHealthRetries}...`);
        await new Promise(resolve => setTimeout(resolve, 5000));
      }
    }
    throw new Error('llama.cpp server failed to become healthy after multiple retries');
  }

  /**
   * Start llama.cpp server with specified model
   */
  async start(model: any): Promise<void> {
    try {
      this.initializeConfig();
      this.logger.info(`Starting llama.cpp server with model: ${model.name}`);

      // Get GPU acceleration flags
      const { gpu, threads } = GPUDetector.buildAccelerationFlags();
      this.logger.info(`GPU acceleration: ${gpu || 'CPU mode'}, Threads: ${threads}`);

      // Get model path - expect model file to be downloaded to models/ directory
      const modelBasePath = path.resolve(__dirname, '../../models', model.id);
      const modelPath = path.join(modelBasePath, model.file || 'model.gguf');
      
      this.logger.info(`Model path: ${modelPath}`);

      // Create process manager
      this.processManager = new ProcessManager();

      // Start llama.cpp server
      const config = this.configLoader.getAppConfig();
      const modelsConfig = this.configLoader.getModelsConfig();
      const llamaCppConfig = modelsConfig.llama_cpp || {};

      try {
        await this.processManager.start({
          modelPath,
          port: this.port,
          gpuFlags: gpu,
          threads,
          contextSize: model.context_size || 4096,
        });

        // Wait for server to be ready (only if process is actually running)
        if (this.processManager.isProcessRunning()) {
          await this.waitForServerReady();
        } else {
          this.logger.warn('llama.cpp process not running, using mock mode for testing');
          this.isMockMode = true;
          this.isRunning = true;
        }
      } catch (processError: any) {
        // If process fails to start, enable mock mode for testing
        if (String(processError).includes('not found')) {
          this.logger.warn('llama-server binary not available, enabling mock mode');
          this.isMockMode = true;
          this.isRunning = true;
        } else {
          throw processError;
        }
      }

      this.logger.info(`llama.cpp server initialized (PID: ${this.processManager.getPID()})`);
    } catch (error) {
      this.logger.error(`Failed to start server: ${error}`);
      throw error;
    }
  }

  /**
   * Stop llama.cpp server
   */
  async stop(): Promise<void> {
    try {
      if (this.processManager) {
        await this.processManager.stop();
        this.isRunning = false;
        this.logger.info('llama.cpp server stopped');
      }
    } catch (error) {
      this.logger.error(`Failed to stop server: ${error}`);
    }
  }

  /**
   * Check if server is running and healthy
   */
  async healthCheck(): Promise<boolean> {
    try {
      const response = await axios.get(`${this.baseUrl}/health`, { timeout: 5000 });
      return response.status === 200;
    } catch {
      return false;
    }
  }

  /**
   * Send prompt to LLM and get response
   */
  async sendPrompt(text: string): Promise<string> {
    try {
      this.initializeConfig();
      
      if (!this.isRunning) {
        throw new Error('llama.cpp server is not running');
      }

      // Return mock response if in mock mode
      if (this.isMockMode) {
        const mockResponse = `[LunaBlue Mock Response]\nYou asked: "${text}"\n\nThis is a placeholder response from mock mode. Install llama.cpp for real responses.\n\nNote: DoNoHarm ethical context has been applied to this interaction.`;
        this.logger.info(`Mock response for prompt: ${text.substring(0, 50)}...`);
        return mockResponse;
      }

      const response = await axios.post(`${this.baseUrl}/v1/completions`, {
        prompt: text,
        max_tokens: 512,
        temperature: 0.7,
        top_p: 0.9,
      });

      return response.data.choices[0].text;
    } catch (error) {
      this.logger.error(`Prompt error: ${error}`);
      throw error;
    }
  }

  /**
   * Stream prompt response (for real-time UI updates)
   */
  async *streamPrompt(text: string): AsyncGenerator<string> {
    try {
      this.initializeConfig();
      
      if (!this.isRunning) {
        throw new Error('llama.cpp server is not running');
      }

      // Return mock streaming response if in mock mode
      if (this.isMockMode) {
        const mockResponse = `[Mock] You asked: "${text}" - DoNoHarm context applied. Install llama.cpp for real responses.`;
        for (const word of mockResponse.split(' ')) {
          yield word + ' ';
          await new Promise(resolve => setTimeout(resolve, 50)); // 50ms delay between words
        }
        return;
      }

      const response = await axios.post(
        `${this.baseUrl}/v1/completions`,
        {
          prompt: text,
          max_tokens: 512,
          temperature: 0.7,
          stream: true,
        },
        { responseType: 'stream' }
      );

      for await (const chunk of response.data) {
        const lines = chunk.toString().split('\n');
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              if (data.choices[0].text) {
                yield data.choices[0].text;
              }
            } catch {
              // Skip invalid JSON lines
            }
          }
        }
      }
    } catch (error) {
      this.logger.error(`Stream error: ${error}`);
      throw error;
    }
  }

  /**
   * Get server status and model info
   */
  async getStatus(): Promise<any> {
    try {
      const response = await axios.get(`${this.baseUrl}/health`);
      return {
        isRunning: this.isRunning,
        baseUrl: this.baseUrl,
        port: this.port,
        ...response.data
      };
    } catch (error) {
      this.logger.error(`Status check error: ${error}`);
      return { isRunning: false, error: String(error) };
    }
  }
}
