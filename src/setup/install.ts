import path from 'path';
import { fileURLToPath } from 'url';
import fs from 'fs';
import { EnvironmentValidator } from '../utils/environment.js';
import { ModelDownloader } from '../utils/modelDownloader.js';
import { ConfigLoader } from '../orchestrator/configLoader.js';
import Logger from '../utils/logging.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const logger = Logger.getLogger('Installer');

/**
 * Installation script for LunaBlue
 * Performs validation and initial setup
 */
async function install(): Promise<void> {
  try {
    logger.info('================================================');
    logger.info('LunaBlue Installation Script');
    logger.info('================================================\n');

    // Step 1: Validate environment
    logger.info('Step 1: Validating environment...');
    const valid = await EnvironmentValidator.validateAll();
    if (!valid) {
      throw new Error('Environment validation failed');
    }
    logger.info('✓ Environment validated\n');

    // Step 2: Create required directories
    logger.info('Step 2: Creating directory structure...');
    const dirs = [
      path.join(__dirname, '../../models'),
      path.join(__dirname, '../../DoNoHarm'),
      path.join(__dirname, '../../logs'),
      path.join(__dirname, '../../temp'),
    ];

    for (const dir of dirs) {
      fs.mkdirSync(dir, { recursive: true });
      logger.info(`✓ Created directory: ${dir}`);
    }
    logger.info('');

    // Step 3: Verify configurations
    logger.info('Step 3: Verifying configuration files...');
    const configLoader = new ConfigLoader();
    await configLoader.load();
    logger.info('✓ Configuration files loaded\n');

    // Step 4: Setup DoNoHarm knowledge base
    logger.info('Step 4: Setting up DoNoHarm knowledge base...');
    await setupDoNoHarm();
    logger.info('✓ DoNoHarm initialized\n');

    logger.info('================================================');
    logger.info('✓ Installation completed successfully!');
    logger.info('================================================\n');
    logger.info('Next steps:');
    logger.info('1. Run: npm run setup:models  (to download models)');
    logger.info('2. Run: npm start              (to start the application)\n');
  } catch (error) {
    logger.error(`Installation failed: ${error}`);
    process.exit(1);
  }
}

/**
 * Setup DoNoHarm knowledge base directory with starter templates
 */
async function setupDoNoHarm(): Promise<void> {
  const donoHarmDir = path.join(__dirname, '../../DoNoHarm');

  // Create README
  const readmePath = path.join(donoHarmDir, 'README.md');
  if (!fs.existsSync(readmePath)) {
    fs.writeFileSync(
      readmePath,
      `# DoNoHarm Knowledge Base

This directory contains markdown files that are loaded into LunaBlueAI's context at startup.

## Purpose
These files define guidelines, values, and contextual information that LunaBlueAI uses to:
- Maintain consistent behavior and values
- Provide appropriate responses
- Avoid harmful outputs
- Understand context and constraints

## Adding Custom Guidelines
1. Create a new markdown file in this directory
2. Write your guidelines or knowledge in markdown format
3. Restart LunaBlueAI to load the new content

## Example Files
- guidelines.md - General usage guidelines
- values.md - Core values and principles
`,
    );
    logger.info(`✓ Created DoNoHarm/README.md`);
  }

  // Create guidelines template
  const guidelinesPath = path.join(donoHarmDir, 'guidelines.md');
  if (!fs.existsSync(guidelinesPath)) {
    fs.writeFileSync(
      guidelinesPath,
      `# LunaBlueAI Usage Guidelines

## General Principles
- Be helpful, harmless, and honest
- Provide accurate and up-to-date information
- Acknowledge limitations and uncertainties
- Respect privacy and confidentiality

## Content Guidelines
- Do not generate content that violates laws or regulations
- Do not create content designed to deceive
- Do not generate content that promotes harm
- Do not access or transmit sensitive personal information

## Response Style
- Use clear, professional language
- Provide concise and relevant responses
- Offer citations and sources when applicable
- Suggest alternatives when unable to help
`,
    );
    logger.info(`✓ Created DoNoHarm/guidelines.md`);
  }

  // Create values template
  const valuesPath = path.join(donoHarmDir, 'values.md');
  if (!fs.existsSync(valuesPath)) {
    fs.writeFileSync(
      valuesPath,
      `# LunaBlueAI Core Values

## Accuracy
- Strive for factual correctness
- Indicate uncertainty clearly
- Update responses as new information becomes available

## Transparency
- Explain reasoning when relevant
- Disclose limitations and constraints
- Be clear about capabilities and boundaries

## Responsibility
- Consider consequences of responses
- Maintain ethical standards
- Support human agency and autonomy
`,
    );
    logger.info(`✓ Created DoNoHarm/values.md`);
  }
}

// Run installation
install().catch(error => {
  console.error('Installation error:', error);
  process.exit(1);
});
