import path from 'path';
import { fileURLToPath } from 'url';
import { ConfigLoader } from '../src/orchestrator/configLoader';
import { ModelDownloader } from '../src/utils/modelDownloader';
import Logger from '../src/utils/logging';
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const logger = Logger.getLogger('ModelSetup');
/**
 * Setup models - Download and verify GGUF models from HuggingFace
 */
async function setupModels() {
    try {
        logger.info('================================================');
        logger.info('LunaBlue Model Setup');
        logger.info('================================================\n');
        // Load configuration
        logger.info('Loading configuration...');
        const configLoader = new ConfigLoader();
        await configLoader.load();
        const models = configLoader.getAllModels();
        const config = configLoader.getModelsConfig();
        logger.info(`✓ Found ${models.length} model(s) to setup\n`);
        // Download each model
        for (const model of models) {
            if (!model.active) {
                logger.info(`Skipping inactive model: ${model.name}`);
                continue;
            }
            logger.info(`Setting up model: ${model.name}`);
            logger.info(`  Repository: ${model.repository}`);
            logger.info(`  File: ${model.filename}`);
            logger.info(`  Size: ${Math.round((2.0 * 1024) / 1024)} MB (estimated)`);
            try {
                const targetPath = path.join(__dirname, '../../', model.local_path);
                // Download model
                await ModelDownloader.downloadFromHuggingFace(model.repository, model.filename, targetPath, (progress) => {
                    process.stdout.write(`  Download: ${progress}%\r`);
                });
                logger.info(`  ✓ Model downloaded successfully\n`);
            }
            catch (error) {
                logger.error(`  ✗ Failed to download model: ${error}`);
                logger.info('  Note: You can download manually and place in models/ directory\n');
            }
        }
        logger.info('================================================');
        logger.info('✓ Model setup completed!');
        logger.info('================================================\n');
        logger.info('Next step: npm start\n');
    }
    catch (error) {
        logger.error(`Model setup failed: ${error}`);
        process.exit(1);
    }
}
// Run setup
setupModels().catch(error => {
    console.error('Setup error:', error);
    process.exit(1);
});
//# sourceMappingURL=setupModels.js.map