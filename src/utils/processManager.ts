import { spawn, ChildProcess } from 'child_process';
import path from 'path';
import { fileURLToPath } from 'url';
import fs from 'fs';
import Logger from './logging.js';

const logger = Logger.getLogger('ProcessManager');
const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * Manager for llama.cpp subprocess lifecycle
 */
export class ProcessManager {
  private process: ChildProcess | null = null;
  private stdout: string[] = [];
  private stderr: string[] = [];
  private isRunning = false;
  private isMockMode = false;

  /**
   * Start llama.cpp server process
   */
  async start(config: {
    modelPath: string;
    port: number;
    gpuFlags: string;
    threads: number;
    contextSize: number;
  }): Promise<void> {
    return new Promise((resolve, reject) => {
      try {
        // Use absolute path to locally built llama-server if available
        const projectRoot = process.cwd();
        const localLlamaServerWindows = projectRoot + '\\llama.cpp\\llama-server.exe';
        const localLlamaServerUnix = projectRoot + '/llama.cpp/llama-server';

        let llamaServerPath = 'llama-server'; // Default fallback

        // Try Windows path first
        try {
          if (fs.existsSync(localLlamaServerWindows)) {
            llamaServerPath = localLlamaServerWindows;
            logger.info(`[FOUND] Using local Windows llama-server: ${llamaServerPath}`);
          } else if (fs.existsSync(localLlamaServerUnix)) {
            llamaServerPath = localLlamaServerUnix;
            logger.info(`[FOUND] Using local Unix llama-server: ${llamaServerPath}`);
          } else {
            logger.warn(`[NOT FOUND] Checking: ${localLlamaServerWindows}`);
            logger.warn(`[NOT FOUND] Checking: ${localLlamaServerUnix}`);
            logger.info(`[FALLBACK] Using system PATH llama-server`);
          }
        } catch (err) {
          logger.error(`[ERROR] Exception checking files: ${err}`);
          logger.info(`[FALLBACK] Using system PATH llama-server`);
        }

        // Construct llama-server command
        const args = [
          '-m', config.modelPath,
          '--port', String(config.port),
          '--threads', String(config.threads),
          '-c', String(config.contextSize),
        ];

        // Add GPU flags if available (split by space if string)
        if (config.gpuFlags) {
          const gpuArgs = config.gpuFlags.split(/\s+/).filter((arg: string) => arg.length > 0);
          args.push(...gpuArgs);
        }

        logger.info(`[SPAWN] Starting with args: ${args.join(' ')}`);

        this.process = spawn(llamaServerPath, args, {
          stdio: ['pipe', 'pipe', 'pipe'],
          detached: false,  // Keep process attached to parent for proper cleanup
        });

        let resolved = false;

        // Capture stdout
        this.process.stdout?.on('data', (data) => {
          const line = data.toString();
          this.stdout.push(line);
          logger.debug(`llama-server stdout: ${line.trim()}`);

          // Check if server is ready
          if ((line.includes('listening on') || line.includes('Ready')) && !resolved) {
            resolved = true;
            this.isRunning = true;
            resolve();
          }
        });

        // Capture stderr
        this.process.stderr?.on('data', (data) => {
          const line = data.toString();
          this.stderr.push(line);
          logger.warn(`llama-server stderr: ${line.trim()}`);

          // Check if server is ready (stderr also includes startup messages)
          if ((line.includes('listening on') || line.includes('Ready')) && !resolved) {
            resolved = true;
            this.isRunning = true;
            resolve();
          }

          // Log any error messages for debugging
          if (line.toLowerCase().includes('error') || line.toLowerCase().includes('fatal')) {
            logger.error(`llama-server error output: ${line.trim()}`);
          }
        });

        // Handle process exit
        this.process.on('exit', (code, signal) => {
          this.isRunning = false;
          logger.info(`llama-server exited with code ${code}, signal ${signal}`);
          
          // Log last stderr lines for debugging process exit
          if (this.stderr.length > 0) {
            const lastErrors = this.stderr.slice(-5).join(' | ');
            logger.info(`Last stderr output: ${lastErrors}`);
          }
        });

        this.process.on('error', (error) => {
          this.isRunning = false;
          const errorMsg = String(error);
          
          // Handle ENOENT (binary not found)
          if (errorMsg.includes('ENOENT')) {
            logger.warn('llama-server binary not found. Install llama.cpp or add to PATH.');
            logger.warn('Phase 2 demo mode enabled - using mock responses for testing.');
            // Set mock mode flag
            this.isMockMode = true;
            this.isRunning = true;
            if (!resolved) {
              resolved = true;
              resolve();
            }
          } else {
            logger.error(`Failed to start llama-server: ${error}`);
            if (!resolved) {
              resolved = true;
              reject(error);
            }
          }
        });

        // Timeout if server doesn't start within 60 seconds (model loading can be slow)
        const startupTimeout = setTimeout(() => {
          if (!this.isRunning && this.process && !resolved) {
            resolved = true;
            reject(new Error('llama-server startup timeout - model loading exceeded 60 seconds'));
          }
        }, 60000);
      } catch (error) {
        logger.error(`Error spawning llama-server: ${error}`);
        reject(error);
      }
    });
  }

  /**
   * Stop llama.cpp server process
   */
  async stop(): Promise<void> {
    return new Promise((resolve) => {
      if (!this.process) {
        resolve();
        return;
      }

      logger.info('Stopping llama-server...');
      this.isRunning = false;

      // Send SIGTERM first
      this.process.kill('SIGTERM');

      // Force kill after 5 seconds if still running
      const forceKillTimeout = setTimeout(() => {
        if (this.process) {
          logger.warn('Force killing llama-server...');
          this.process.kill('SIGKILL');
        }
      }, 5000);

      this.process.on('exit', () => {
        clearTimeout(forceKillTimeout);
        this.process = null;
        logger.info('llama-server stopped');
        resolve();
      });
    });
  }

  /**
   * Check if process is running
   */
  isProcessRunning(): boolean {
    return this.isRunning && this.process !== null && !this.isMockMode;
  }
  /**
   * Check if in mock mode
   */
  isMockModeEnabled(): boolean {
    return this.isMockMode;
  }
  /**
   * Check if in mock mode (binary not found)
   */
  isMockModeActive(): boolean {
    return this.isMockMode;
  }

  /**
   * Get last N lines of output
   */
  getOutput(lines: number = 50): string {
    const allOutput = [...this.stdout, ...this.stderr];
    return allOutput.slice(-lines).join('');
  }

  /**
   * Get process PID
   */
  getPID(): number | null {
    return this.process?.pid || null;
  }
}
