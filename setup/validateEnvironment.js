import { EnvironmentValidator } from '../src/utils/environment';
import Logger from '../src/utils/logging';
const logger = Logger.getLogger('EnvironmentCheck');
/**
 * Validate environment before installation
 */
async function validateEnvironment() {
    try {
        logger.info('================================================');
        logger.info('LunaBlue Environment Validation');
        logger.info('================================================\n');
        logger.info('Checking system requirements...\n');
        // OS validation
        try {
            const os = EnvironmentValidator.validateOS();
            logger.info(`✓ OS: ${os}`);
        }
        catch (error) {
            logger.error(`✗ OS validation failed: ${error}`);
        }
        // Disk space validation
        try {
            const diskOK = EnvironmentValidator.validateDiskSpace();
            logger.info(diskOK ? '✓ Disk space: OK (8GB+ available)' : '✗ Insufficient disk space');
        }
        catch (error) {
            logger.error(`✗ Disk space check failed: ${error}`);
        }
        // Permissions validation
        try {
            const permsOK = EnvironmentValidator.validatePermissions();
            logger.info(permsOK ? '✓ Permissions: OK' : '✗ Permission check failed');
        }
        catch (error) {
            logger.error(`✗ Permission check failed: ${error}`);
        }
        // GPU validation
        try {
            const gpu = await EnvironmentValidator.validateGPU();
            logger.info(`✓ GPU: ${gpu.hasGPU ? gpu.type : 'None (CPU fallback)'}`);
        }
        catch (error) {
            logger.error(`✗ GPU check failed: ${error}`);
        }
        logger.info('\n================================================');
        logger.info('✓ Environment validation complete');
        logger.info('================================================\n');
    }
    catch (error) {
        logger.error(`Validation failed: ${error}`);
        process.exit(1);
    }
}
// Run validation
validateEnvironment().catch(error => {
    console.error('Validation error:', error);
    process.exit(1);
});
//# sourceMappingURL=validateEnvironment.js.map