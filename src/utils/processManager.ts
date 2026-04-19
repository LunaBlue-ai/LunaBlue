import { spawn, ChildProcess } from 'child_process';
import path from 'path';
import { fileURLToPath } from 'url';
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
        // Construct llama-server command
        // Note: Assumes llama.cpp is installed globally or in PATH
        const args = [
          '-m', config.modelPath,
          '-p', '8000',
          `--port ${config.port}`,
          '--threads', String(config.threads),
          '-c', String(config.contextSize),
        ];

        if (config.gpuFlags) {
          args.push(config.gpuFlags);
        }

        logger.info(`Starting llama.cpp server with command: llama-server ${args.join(' ')}`);

        this.process = spawn('llama-server', args, {
          stdio: ['pipe', 'pipe', 'pipe'],
          timeout: 30000,
        });

        // Capture stdout
        this.process.stdout?.on('data', (data) => {
          const line = data.toString();
          this.stdout.push(line);
          logger.debug(`llama-server: ${line.trim()}`);

          // Check if server is ready
          if (line.includes('listening on') || line.includes('Ready')) {
            this.isRunning = true;
            resolve();
          }
        });

        // Capture stderr
        this.process.stderr?.on('data', (data) => {
          const line = data.toString();
          this.stderr.push(line);
          logger.warn(`llama-server stderr: ${line.trim()}`);
        });

        // Handle process exit
        this.process.on('exit', (code, signal) => {
          this.isRunning = false;
          logger.info(`llama-server exited with code ${code}, signal ${signal}`);
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
            resolve();
          } else {
            logger.error(`Failed to start llama-server: ${error}`);
            reject(error);
          }
        });

        // Timeout if server doesn't start within 30 seconds
        setTimeout(() => {
          if (!this.isRunning && this.process) {
            reject(new Error('llama-server startup timeout'));
          }
        }, 30000);
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
