import { execSync } from 'child_process';
import os from 'os';
import Logger from './logging.js';

const logger = Logger.getLogger('GPUDetector');

/**
 * GPU capability detection across multiple platforms
 */
export class GPUDetector {
  /**
   * Detect NVIDIA CUDA capability
   */
  static detectNVIDIA(): { available: boolean; vram?: number; version?: string } {
    try {
      const output = execSync('nvidia-smi --query-gpu=memory.total --format=csv,noheader', { 
        encoding: 'utf-8',
        timeout: 5000 
      });
      const vram = parseInt(output.trim().split(' ')[0]);
      logger.info(`NVIDIA GPU detected: ${vram}MB VRAM available`);
      return { available: true, vram };
    } catch {
      return { available: false };
    }
  }

  /**
   * Detect AMD ROCm capability
   */
  static detectAMD(): { available: boolean; vram?: number } {
    try {
      const output = execSync('rocm-smi --showmeminfo', { 
        encoding: 'utf-8',
        timeout: 5000 
      });
      if (output.includes('GPU')) {
        logger.info('AMD ROCm GPU detected');
        return { available: true };
      }
      return { available: false };
    } catch {
      return { available: false };
    }
  }

  /**
   * Detect Apple Metal capability
   */
  static detectMetal(): { available: boolean } {
    try {
      const output = execSync('system_profiler SPDisplaysDataType', { 
        encoding: 'utf-8',
        timeout: 5000 
      });
      if (output.includes('GPU')) {
        logger.info('Apple Metal GPU detected');
        return { available: true };
      }
      return { available: false };
    } catch {
      return { available: false };
    }
  }

  /**
   * Auto-detect available GPU and return configuration
   */
  static autoDetect(): string {
    const platform = process.platform;

    if (platform === 'win32' || platform === 'linux') {
      const nvidia = this.detectNVIDIA();
      if (nvidia.available) {
        return `--gpu-layers 35`; // Default: offload 35 layers to GPU
      }

      const amd = this.detectAMD();
      if (amd.available) {
        return `--gpu-layers 30`;
      }
    }

    if (platform === 'darwin') {
      const metal = this.detectMetal();
      if (metal.available) {
        return `--metal`;
      }
    }

    logger.info('No GPU detected, using CPU mode');
    return '';
  }

  /**
   * Get GPU recommendations based on VRAM
   */
  static getGPURecommendations(vram: number): number {
    // Conservative estimates: allocate ~60% of VRAM to model
    if (vram >= 24000) return 40; // 24GB+ → 40 layers
    if (vram >= 12000) return 32; // 12GB+ → 32 layers
    if (vram >= 8000) return 24;  // 8GB+ → 24 layers
    if (vram >= 4000) return 16;  // 4GB+ → 16 layers
    return 0; // CPU fallback for <4GB
  }

  /**
   * Detect CPU core count for threading
   */
  static getCoreCount(): number {
    return os.cpus().length;
  }

  /**
   * Build complete llama.cpp acceleration flags
   */
  static buildAccelerationFlags(): { gpu: string; threads: number } {
    const gpu = this.autoDetect();
    const threads = Math.max(1, this.getCoreCount() - 1);

    logger.info(`GPU flags: ${gpu || '(CPU mode)'}, Threads: ${threads}`);
    return { gpu, threads };
  }
}
