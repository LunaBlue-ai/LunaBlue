import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import Logger from '../utils/logging.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * ConfigLoader - Loads and manages application and model configurations
 */
export class ConfigLoader {
  private appConfig: any = null;
  private modelsConfig: any = null;
  private logger = Logger.getLogger('ConfigLoader');
  private basePath = path.resolve(__dirname, '../../');

  /**
   * Load configurations from disk
   */
  async load(): Promise<void> {
    try {
      await this.loadAppConfig();
      await this.loadModelsConfig();
      this.logger.info('All configurations loaded successfully');
    } catch (error) {
      this.logger.error(`Failed to load configurations: ${error}`);
      throw error;
    }
  }

  /**
   * Load application configuration
   */
  private async loadAppConfig(): Promise<void> {
    try {
      const configPath = path.join(this.basePath, 'config', 'app.config.json');
      const content = fs.readFileSync(configPath, 'utf-8');
      this.appConfig = JSON.parse(content);
      this.logger.info(`App config loaded from ${configPath}`);
    } catch (error) {
      this.logger.error(`Failed to load app config: ${error}`);
      throw error;
    }
  }

  /**
   * Load models configuration
   */
  private async loadModelsConfig(): Promise<void> {
    try {
      const configPath = path.join(this.basePath, 'config', 'models.config.json');
      const content = fs.readFileSync(configPath, 'utf-8');
      this.modelsConfig = JSON.parse(content);
      this.logger.info(`Models config loaded from ${configPath}`);
    } catch (error) {
      this.logger.error(`Failed to load models config: ${error}`);
      throw error;
    }
  }

  /**
   * Get application configuration
   */
  getAppConfig(): any {
    if (!this.appConfig) {
      throw new Error('App config not loaded. Call load() first.');
    }
    return this.appConfig;
  }

  /**
   * Get models configuration
   */
  getModelsConfig(): any {
    if (!this.modelsConfig) {
      throw new Error('Models config not loaded. Call load() first.');
    }
    return this.modelsConfig;
  }

  /**
   * Get all available models
   */
  getAllModels(): any[] {
    if (!this.modelsConfig) {
      throw new Error('Models config not loaded. Call load() first.');
    }
    return this.modelsConfig.models || [];
  }

  /**
   * Get default model
   */
  getDefaultModel(): any {
    if (!this.modelsConfig) {
      throw new Error('Models config not loaded. Call load() first.');
    }
    const defaultId = this.modelsConfig.default_model;
    const model = this.modelsConfig.models.find((m: any) => m.id === defaultId);
    if (!model) {
      throw new Error(`Default model not found: ${defaultId}`);
    }
    return model;
  }

  /**
   * Get model by ID
   */
  getModel(modelId: string): any {
    const models = this.getAllModels();
    const model = models.find(m => m.id === modelId);
    if (!model) {
      throw new Error(`Model not found: ${modelId}`);
    }
    return model;
  }

  /**
   * Get llama.cpp configuration
   */
  getLlamaCppConfig(): any {
    if (!this.modelsConfig) {
      throw new Error('Models config not loaded. Call load() first.');
    }
    return this.modelsConfig.llama_cpp || {};
  }

  /**
   * Get DoNoHarm configuration
   */
  getDoNoHarmConfig(): any {
    if (!this.modelsConfig) {
      throw new Error('Models config not loaded. Call load() first.');
    }
    return this.modelsConfig.donoharm || {};
  }
}
