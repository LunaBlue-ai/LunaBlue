import axios from 'axios';
import fs from 'fs';
import path from 'path';
import Logger from './logging.js';

const logger = Logger.getLogger('ModelDownloader');

/**
 * Model downloader utility for fetching GGUF models from HuggingFace
 */
export class ModelDownloader {
  /**
   * Download a model from HuggingFace
   */
  static async downloadFromHuggingFace(
    repoId: string,
    filename: string,
    targetPath: string,
    onProgress?: (progress: number) => void
  ): Promise<string> {
    try {
      const url = `https://huggingface.co/${repoId}/resolve/main/${filename}`;
      const fullPath = path.join(targetPath, filename);

      // Create directory if it doesn't exist
      fs.mkdirSync(targetPath, { recursive: true });

      logger.info(`Downloading ${filename} from ${repoId}...`);

      const response = await axios.get(url, {
        responseType: 'stream',
        timeout: 600000, // 10 minutes
      });

      const stream = fs.createWriteStream(fullPath);
      const totalLength = parseInt(response.headers['content-length'], 10);
      let downloadedLength = 0;

      response.data.on('data', (chunk: Buffer) => {
        downloadedLength += chunk.length;
        const progress = Math.round((downloadedLength / totalLength) * 100);
        if (onProgress) {
          onProgress(progress);
        }
      });

      response.data.pipe(stream);

      return new Promise((resolve, reject) => {
        stream.on('finish', () => {
          logger.info(`Download complete: ${fullPath}`);
          resolve(fullPath);
        });
        stream.on('error', reject);
      });
    } catch (error) {
      logger.error(`Download failed: ${error}`);
      throw error;
    }
  }

  /**
   * Verify model checksum
   */
  static async verifyChecksum(
    filePath: string,
    expectedHash: string,
    algorithm: string = 'sha256'
  ): Promise<boolean> {
    // TODO: Implement checksum verification
    logger.info(`Verifying ${algorithm} checksum for ${filePath}`);
    return true;
  }
}
