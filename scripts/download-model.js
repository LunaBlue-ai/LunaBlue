#!/usr/bin/env node
/**
 * Download Phi-3 Mini GGUF model from HuggingFace
 */
const https = require('https');
const fs = require('fs');
const path = require('path');

// Model configuration
const MODEL_REPO = 'microsoft/Phi-3-mini-4k-instruct-gguf';
const MODEL_FILE = 'Phi-3-mini-4k-instruct-q4.gguf'; // Quantized version (faster, smaller)
const DOWNLOAD_URL = `https://huggingface.co/${MODEL_REPO}/resolve/main/${MODEL_FILE}?download=true`;
const MODEL_DIR = path.join(__dirname, 'models', 'phi-3-mini-4k-instruct');
const OUTPUT_FILE = path.join(MODEL_DIR, 'model.gguf');

async function downloadModel() {
  // Create directory if it doesn't exist
  if (!fs.existsSync(MODEL_DIR)) {
    fs.mkdirSync(MODEL_DIR, { recursive: true });
    console.log(`Created directory: ${MODEL_DIR}`);
  }

  // Check if model already exists
  if (fs.existsSync(OUTPUT_FILE)) {
    console.log(`Model already exists: ${OUTPUT_FILE}`);
    return;
  }

  console.log(`Downloading Phi-3 Mini model...`);
  console.log(`From: ${DOWNLOAD_URL}`);
  console.log(`To: ${OUTPUT_FILE}`);
  console.log(`Note: This will download a large file (~8GB for Q4 quantized version)`);
  console.log(`Note: You may want to use a smaller quantized version (Q5_K_M, Q6_K)`);
  console.log('');
  console.log('Starting download... (this will take several minutes)');

  const file = fs.createWriteStream(OUTPUT_FILE);
  let downloadedBytes = 0;
  const startTime = Date.now();

  return new Promise((resolve, reject) => {
    https.get(DOWNLOAD_URL, { timeout: 300000 }, (response) => {
      // Handle redirects
      if (response.statusCode === 301 || response.statusCode === 302) {
        https.get(response.headers.location, (redirectRes) => {
          const totalSize = parseInt(redirectRes.headers['content-length'], 10);
          redirectRes.pipe(file);
          
          redirectRes.on('data', (chunk) => {
            downloadedBytes += chunk.length;
            const percent = ((downloadedBytes / totalSize) * 100).toFixed(1);
            const elapsed = (Date.now() - startTime) / 1000;
            const speed = (downloadedBytes / 1024 / 1024 / elapsed).toFixed(2);
            process.stdout.write(`\rDownloaded: ${percent}% (${(downloadedBytes / 1024 / 1024).toFixed(0)}MB/${(totalSize / 1024 / 1024).toFixed(0)}MB) - Speed: ${speed}MB/s`);
          });

          redirectRes.on('end', () => {
            file.close();
            console.log('\n✓ Download complete');
            console.log(`Model saved to: ${OUTPUT_FILE}`);
            resolve();
          });
        }).on('error', reject);
      } else {
        const totalSize = parseInt(response.headers['content-length'], 10);
        response.pipe(file);
        
        response.on('data', (chunk) => {
          downloadedBytes += chunk.length;
          const percent = ((downloadedBytes / totalSize) * 100).toFixed(1);
          const elapsed = (Date.now() - startTime) / 1000;
          const speed = (downloadedBytes / 1024 / 1024 / elapsed).toFixed(2);
          process.stdout.write(`\rDownloaded: ${percent}% (${(downloadedBytes / 1024 / 1024).toFixed(0)}MB/${(totalSize / 1024 / 1024).toFixed(0)}MB) - Speed: ${speed}MB/s`);
        });

        response.on('end', () => {
          file.close();
          console.log('\n✓ Download complete');
          console.log(`Model saved to: ${OUTPUT_FILE}`);
          resolve();
        });
      }
    }).on('error', (err) => {
      file.close();
      fs.unlink(OUTPUT_FILE, () => {}); // Clean up partial file
      reject(err);
    }).on('timeout', function() {
      this.destroy();
      file.close();
      fs.unlink(OUTPUT_FILE, () => {});
      reject(new Error('Download timeout'));
    });
  });
}

downloadModel()
  .then(() => {
    console.log('\n✓ Model download successful!');
    console.log('You can now run: npm start');
    process.exit(0);
  })
  .catch((err) => {
    console.error('\n✗ Download failed:', err.message);
    console.error('\nAlternative: Download manually from:');
    console.error(`  https://huggingface.co/${MODEL_REPO}`);
    console.error(`\nThen place the model file at: ${OUTPUT_FILE}`);
    process.exit(1);
  });
