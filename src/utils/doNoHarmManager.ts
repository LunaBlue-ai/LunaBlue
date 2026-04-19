import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import Logger from './logging.js';

const logger = Logger.getLogger('DoNoHarmManager');
const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * DoNoHarm - Ethics and safety framework manager
 * Loads knowledge base and injects ethical context into prompts
 */
export class DoNoHarmManager {
  private guidelines: string = '';
  private values: string = '';
  private isLoaded: boolean = false;
  private basePath: string;

  constructor() {
    this.basePath = path.resolve(__dirname, '../../DoNoHarm');
  }

  /**
   * Load DoNoHarm knowledge base from disk
   */
  async load(): Promise<void> {
    try {
      logger.info('Loading DoNoHarm knowledge base...');

      // Load guidelines
      const guidelinesPath = path.join(this.basePath, 'guidelines.md');
      if (fs.existsSync(guidelinesPath)) {
        this.guidelines = fs.readFileSync(guidelinesPath, 'utf-8');
        logger.info('Guidelines loaded successfully');
      } else {
        logger.warn('Guidelines file not found, using empty defaults');
        this.guidelines = this.getDefaultGuidelines();
      }

      // Load values
      const valuesPath = path.join(this.basePath, 'values.md');
      if (fs.existsSync(valuesPath)) {
        this.values = fs.readFileSync(valuesPath, 'utf-8');
        logger.info('Values loaded successfully');
      } else {
        logger.warn('Values file not found, using empty defaults');
        this.values = this.getDefaultValues();
      }

      this.isLoaded = true;
      logger.info('DoNoHarm knowledge base loaded');
    } catch (error) {
      logger.error(`Failed to load DoNoHarm: ${error}`);
      throw error;
    }
  }

  /**
   * Get default guidelines if file not found
   */
  private getDefaultGuidelines(): string {
    return `# LunaBlue Usage Guidelines

## Core Principles
1. Be helpful, harmless, and honest
2. Respect user privacy and data
3. Follow applicable laws and regulations
4. Decline requests for illegal activities
5. Acknowledge limitations and uncertainties

## Content Safety
- No hate speech or discrimination
- No violence or harm promotion
- No sexual content involving minors
- No malware or hacking assistance
- No harassment or bullying`;
  }

  /**
   * Get default values if file not found
   */
  private getDefaultValues(): string {
    return `# LunaBlue Core Values

## Ethical AI
- Transparency in limitations
- Fairness and non-discrimination
- User autonomy and control
- Continuous safety improvement

## User Trust
- Privacy protection
- Honest communication
- Responsible use of information
- Respect for user goals`;
  }

  /**
   * Build system prompt with DoNoHarm context
   */
  buildSystemPrompt(userPrompt: string): string {
    if (!this.isLoaded) {
      logger.warn('DoNoHarm not loaded, using plain user prompt');
      return userPrompt;
    }

    const systemContext = `[SYSTEM CONTEXT - LunaBlue Ethical Framework]

${this.guidelines}

${this.values}

[END SYSTEM CONTEXT]

Remember: Follow these guidelines and values when responding to the user query below.

---

User Query:
${userPrompt}`;

    return systemContext;
  }

  /**
   * Check if response violates guidelines (simple pattern matching)
   */
  checkResponseCompliance(response: string): { compliant: boolean; issues: string[] } {
    const issues: string[] = [];

    // Check for concerning patterns
    const dangerousPatterns = [
      { pattern: /bomb|explosive|detonate/gi, issue: 'Violence/harm' },
      { pattern: /steal|robbery|hack|password/gi, issue: 'Illegal activity' },
      { pattern: /hate|genocide|supremacist/gi, issue: 'Hate speech' },
    ];

    for (const { pattern, issue } of dangerousPatterns) {
      if (pattern.test(response)) {
        issues.push(issue);
      }
    }

    return {
      compliant: issues.length === 0,
      issues,
    };
  }

  /**
   * Get DoNoHarm status for API responses
   */
  getStatus(): {
    enabled: boolean;
    loaded: boolean;
    guidelines: { characters: number };
    values: { characters: number };
  } {
    return {
      enabled: true,
      loaded: this.isLoaded,
      guidelines: { characters: this.guidelines.length },
      values: { characters: this.values.length },
    };
  }

  /**
   * Get guidelines text
   */
  getGuidelines(): string {
    return this.guidelines;
  }

  /**
   * Get values text
   */
  getValues(): string {
    return this.values;
  }

  /**
   * Is loaded flag
   */
  isKnowledgeBaseLoaded(): boolean {
    return this.isLoaded;
  }
}
