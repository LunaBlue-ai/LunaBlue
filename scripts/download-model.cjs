const https = require('https');
const fs = require('fs');
const path = require('path');

// Model configuration
const MODEL_REPO = 'microsoft/Phi-3-mini-4k-instruct-gguf';
const MODEL_FILE = 'Phi-3-mini-4k-instruct-q4.gguf'; // Quantized version (faster, smaller)
const DOWNLOAD_URL = `https://huggingface.co/${MODEL_REPO}/resolve/main/${MODEL_FILE}?download=true`;
const MODEL_DIR = path.join(__dirname, '..', 'models', 'phi-3-mini-4k-instruct');
const OUTPUT_FILE = path.join(MODEL_DIR, 'model.gguf');

async function downloadModel() {
  if (!fs.existsSync(MODEL_DIR)) {
    fs.mkdirSync(MODEL_DIR, { recursive: true });
    console.log(`Created directory: ${MODEL_DIR}`);
  }

  if (fs.existsSync(OUTPUT_FILE)) {
    console.log(`Model already exists: ${OUTPUT_FILE}`);
    return;
  }

  console.log(`Downloading Phi-3 Mini model to ${OUTPUT_FILE}`);
  const file = fs.createWriteStream(OUTPUT_FILE);
  let downloadedBytes = 0;
  const startTime = Date.now();

  return new Promise((resolve, reject) => {
    https.get(DOWNLOAD_URL, { timeout: 300000 }, (response) => {
      if (response.statusCode === 301 || response.statusCode === 302) {
        https.get(response.headers.location, (redirectRes) => {
          const totalSize = parseInt(redirectRes.headers['content-length'], 10) || 0;
          redirectRes.pipe(file);
          redirectRes.on('data', (chunk) => {
            downloadedBytes += chunk.length;
            if (totalSize) {
              const percent = ((downloadedBytes / totalSize) * 100).toFixed(1);
              const elapsed = (Date.now() - startTime) / 1000;
              const speed = (downloadedBytes / 1024 / 1024 / elapsed).toFixed(2);
              process.stdout.write(`\rDownloaded: ${percent}% (${(downloadedBytes / 1024 / 1024).toFixed(1)}MB/${(totalSize / 1024 / 1024).toFixed(1)}MB) - ${speed} MB/s`);
            }
          });

          redirectRes.on('end', () => {
            file.close();
            console.log('\n✓ Download complete');
            resolve();
          });
        }).on('error', reject);
      } else {
        const totalSize = parseInt(response.headers['content-length'], 10) || 0;
        response.pipe(file);
        response.on('data', (chunk) => {
          downloadedBytes += chunk.length;
          if (totalSize) {
            const percent = ((downloadedBytes / totalSize) * 100).toFixed(1);
            const elapsed = (Date.now() - startTime) / 1000;
            const speed = (downloadedBytes / 1024 / 1024 / elapsed).toFixed(2);
            process.stdout.write(`\rDownloaded: ${percent}% (${(downloadedBytes / 1024 / 1024).toFixed(1)}MB/${(totalSize / 1024 / 1024).toFixed(1)}MB) - ${speed} MB/s`);
          }
        });

        response.on('end', () => {
          file.close();
          console.log('\n✓ Download complete');
          resolve();
        });
      }
    }).on('error', (err) => {
      file.close();
      fs.unlink(OUTPUT_FILE, () => {});
      reject(err);
    }).on('timeout', function () {
      this.destroy();
      file.close();
      fs.unlink(OUTPUT_FILE, () => {});
      reject(new Error('Download timed out'));
    });
  });
}

downloadModel()
  .then(() => {
    console.log('\nModel download finished successfully.');
    process.exit(0);
  })
  .catch((err) => {
    console.error('\nDownload failed:', err.message);
    console.error(`\nIf automatic download fails, download manually from https://huggingface.co/${MODEL_REPO} and place the file at ${OUTPUT_FILE}`);
    process.exit(1);
  });
