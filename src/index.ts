import { Orchestrator } from './orchestrator/orchestrator.js';
import { setupAPIServer } from './api/server.js';
import Logger from './utils/logging.js';

const logger = Logger.getLogger('Main');

/**
 * Main entry point for LunaBlue
 */
async function main(): Promise<void> {
  try {
    logger.info('==========================================');
    logger.info('LunaBlue AI Orchestration Layer');
    logger.info('Version 0.1.0');
    logger.info('==========================================');

    // Initialize orchestrator
    const orchestrator = new Orchestrator();
    await orchestrator.initialize();

    // Setup API server
    const app = setupAPIServer(orchestrator);
    const port = 3000;

    app.listen(port, 'localhost', () => {
      logger.info(`LunaBlue API server running on http://localhost:${port}`);
      logger.info('Press Ctrl+C to shutdown');
    });

    // Graceful shutdown
    process.on('SIGINT', async () => {
      logger.info('\nShutting down...');
      await orchestrator.shutdown();
      process.exit(0);
    });
  } catch (error) {
    logger.error(`Fatal error: ${error}`);
    process.exit(1);
  }
}

// Run main
main().catch(error => {
  console.error('Uncaught error:', error);
  process.exit(1);
});
