import Database from 'better-sqlite3';
import path from 'path';
import { fileURLToPath } from 'url';
import fs from 'fs';
import Logger from './logging.js';

const logger = Logger.getLogger('ChatHistory');
const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * ChatHistory - Persistent chat conversation storage
 * Uses SQLite for fast local storage with no external dependencies
 */
export class ChatHistory {
  private db: Database.Database;
  private dbPath: string;

  constructor(dbPath?: string) {
    // Default to data/lunablue.db
    this.dbPath = dbPath || path.join(__dirname, '..', '..', 'data', 'lunablue.db');
    
    // Ensure data directory exists
    const dataDir = path.dirname(this.dbPath);
    try {
      if (!fs.existsSync(dataDir)) {
        fs.mkdirSync(dataDir, { recursive: true });
      }
    } catch (e) {
      logger.warn(`Could not create data directory: ${e}`);
    }

    // Initialize database connection
    this.db = new Database(this.dbPath);
    this.db.pragma('journal_mode = WAL'); // Write-Ahead Logging for better concurrency
    
    logger.info(`Chat history database initialized: ${this.dbPath}`);
    
    // Initialize schema
    this.initializeSchema();
  }

  /**
   * Initialize database tables
   */
  private initializeSchema(): void {
    try {
      // Sessions table
      this.db.exec(`
        CREATE TABLE IF NOT EXISTS sessions (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          title TEXT DEFAULT 'New Chat',
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL,
          model_id TEXT,
          system_prompt TEXT,
          metadata TEXT,
          archived BOOLEAN DEFAULT 0
        );
        
        CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
        CREATE INDEX IF NOT EXISTS idx_sessions_created ON sessions(created_at DESC);
      `);

      // Messages table  
      this.db.exec(`
        CREATE TABLE IF NOT EXISTS messages (
          id TEXT PRIMARY KEY,
          session_id TEXT NOT NULL,
          role TEXT NOT NULL,
          content TEXT NOT NULL,
          model_id TEXT,
          tokens_input INTEGER,
          tokens_output INTEGER,
          created_at INTEGER NOT NULL,
          FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );
        
        CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
        CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at DESC);
      `);

      // Models history table
      this.db.exec(`
        CREATE TABLE IF NOT EXISTS model_usage (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          model_id TEXT NOT NULL,
          prompt_count INTEGER DEFAULT 0,
          total_tokens_input INTEGER DEFAULT 0,
          total_tokens_output INTEGER DEFAULT 0,
          total_duration_ms INTEGER DEFAULT 0,
          last_used INTEGER NOT NULL,
          created_at INTEGER NOT NULL
        );
        
        CREATE INDEX IF NOT EXISTS idx_model_usage_user ON model_usage(user_id);
      `);

      logger.info('Chat history schema initialized');
    } catch (error) {
      logger.error(`Failed to initialize schema: ${error}`);
    }
  }

  /**
   * Create a new chat session
   */
  createSession(sessionId: string, userId: string, title: string = 'New Chat', modelId?: string): void {
    try {
      const stmt = this.db.prepare(`
        INSERT INTO sessions (id, user_id, title, created_at, updated_at, model_id)
        VALUES (?, ?, ?, ?, ?, ?)
      `);
      
      const now = Date.now();
      stmt.run(sessionId, userId, title, now, now, modelId || null);
      logger.debug(`Session created: ${sessionId}`);
    } catch (error) {
      logger.error(`Failed to create session: ${error}`);
    }
  }

  /**
   * Add a message to a session
   */
  addMessage(messageId: string, sessionId: string, role: 'user' | 'assistant', content: string, modelId?: string, tokens?: { input: number; output: number }): void {
    try {
      const stmt = this.db.prepare(`
        INSERT INTO messages (id, session_id, role, content, model_id, tokens_input, tokens_output, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
      `);
      
      stmt.run(
        messageId,
        sessionId,
        role,
        content,
        modelId || null,
        tokens?.input || null,
        tokens?.output || null,
        Date.now()
      );
      
      // Update session's updated_at timestamp
      this.db.prepare('UPDATE sessions SET updated_at = ? WHERE id = ?').run(Date.now(), sessionId);
      
      logger.debug(`Message added to session ${sessionId}`);
    } catch (error) {
      logger.error(`Failed to add message: ${error}`);
    }
  }

  /**
   * Get all sessions for a user
   */
  getUserSessions(userId: string, limit: number = 50, offset: number = 0): any[] {
    try {
      const stmt = this.db.prepare(`
        SELECT id, title, created_at, updated_at, model_id, archived
        FROM sessions
        WHERE user_id = ? AND archived = 0
        ORDER BY updated_at DESC
        LIMIT ? OFFSET ?
      `);
      
      return stmt.all(userId, limit, offset) as any[];
    } catch (error) {
      logger.error(`Failed to get user sessions: ${error}`);
      return [];
    }
  }

  /**
   * Get messages from a session
   */
  getSessionMessages(sessionId: string, limit: number = 50, offset: number = 0): any[] {
    try {
      const stmt = this.db.prepare(`
        SELECT id, role, content, model_id, tokens_input, tokens_output, created_at
        FROM messages
        WHERE session_id = ?
        ORDER BY created_at ASC
        LIMIT ? OFFSET ?
      `);
      
      return stmt.all(sessionId, limit, offset) as any[];
    } catch (error) {
      logger.error(`Failed to get session messages: ${error}`);
      return [];
    }
  }

  /**
   * Get a specific session
   */
  getSession(sessionId: string): any | null {
    try {
      const stmt = this.db.prepare(`
        SELECT id, user_id, title, created_at, updated_at, model_id, system_prompt, archived
        FROM sessions
        WHERE id = ?
      `);
      
      return (stmt.get(sessionId) as any) || null;
    } catch (error) {
      logger.error(`Failed to get session: ${error}`);
      return null;
    }
  }

  /**
   * Update session title
   */
  updateSessionTitle(sessionId: string, title: string): void {
    try {
      this.db.prepare('UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?').run(title, Date.now(), sessionId);
      logger.debug(`Session title updated: ${sessionId}`);
    } catch (error) {
      logger.error(`Failed to update session title: ${error}`);
    }
  }

  /**
   * Archive a session
   */
  archiveSession(sessionId: string): void {
    try {
      this.db.prepare('UPDATE sessions SET archived = 1, updated_at = ? WHERE id = ?').run(Date.now(), sessionId);
      logger.debug(`Session archived: ${sessionId}`);
    } catch (error) {
      logger.error(`Failed to archive session: ${error}`);
    }
  }

  /**
   * Delete a session and its messages
   */
  deleteSession(sessionId: string): void {
    try {
      this.db.prepare('DELETE FROM messages WHERE session_id = ?').run(sessionId);
      this.db.prepare('DELETE FROM sessions WHERE id = ?').run(sessionId);
      logger.debug(`Session deleted: ${sessionId}`);
    } catch (error) {
      logger.error(`Failed to delete session: ${error}`);
    }
  }

  /**
   * Record model usage statistics
   */
  recordModelUsage(userId: string, modelId: string, durationMs: number, tokens?: { input: number; output: number }): void {
    try {
      const existing = this.db.prepare('SELECT * FROM model_usage WHERE user_id = ? AND model_id = ?').get(userId, modelId);
      
      if (existing) {
        this.db.prepare(`
          UPDATE model_usage 
          SET prompt_count = prompt_count + 1,
              total_tokens_input = total_tokens_input + ?,
              total_tokens_output = total_tokens_output + ?,
              total_duration_ms = total_duration_ms + ?,
              last_used = ?
          WHERE user_id = ? AND model_id = ?
        `).run(
          tokens?.input || 0,
          tokens?.output || 0,
          durationMs,
          Date.now(),
          userId,
          modelId
        );
      } else {
        const id = `usage-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
        this.db.prepare(`
          INSERT INTO model_usage (id, user_id, model_id, prompt_count, total_tokens_input, total_tokens_output, total_duration_ms, last_used, created_at)
          VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?)
        `).run(id, userId, modelId, tokens?.input || 0, tokens?.output || 0, durationMs, Date.now(), Date.now());
      }
      logger.debug(`Model usage recorded: ${userId} / ${modelId}`);
    } catch (error) {
      logger.error(`Failed to record model usage: ${error}`);
    }
  }

  /**
   * Get user's model usage statistics
   */
  getUserModelStats(userId: string): any[] {
    try {
      const stmt = this.db.prepare(`
        SELECT model_id, prompt_count, total_tokens_input, total_tokens_output, total_duration_ms, last_used
        FROM model_usage
        WHERE user_id = ?
        ORDER BY last_used DESC
      `);
      
      return stmt.all(userId) as any[];
    } catch (error) {
      logger.error(`Failed to get model stats: ${error}`);
      return [];
    }
  }

  /**
   * Search conversation history
   */
  searchMessages(userId: string, query: string, limit: number = 20): any[] {
    try {
      // Search for messages from sessions belonging to the user containing the query
      const stmt = this.db.prepare(`
        SELECT m.id, m.session_id, m.role, m.content, m.created_at, s.title
        FROM messages m
        JOIN sessions s ON m.session_id = s.id
        WHERE s.user_id = ? AND (m.content LIKE ? OR s.title LIKE ?)
        ORDER BY m.created_at DESC
        LIMIT ?
      `);
      
      const pattern = `%${query}%`;
      return stmt.all(userId, pattern, pattern, limit) as any[];
    } catch (error) {
      logger.error(`Failed to search messages: ${error}`);
      return [];
    }
  }

  /**
   * Get database statistics
   */
  getStats(): any {
    try {
      return {
        sessions: (this.db.prepare('SELECT COUNT(*) as count FROM sessions').get() as any).count,
        messages: (this.db.prepare('SELECT COUNT(*) as count FROM messages').get() as any).count,
        users: (this.db.prepare('SELECT COUNT(DISTINCT user_id) as count FROM sessions').get() as any).count,
        dbPath: this.dbPath,
      };
    } catch (error) {
      logger.error(`Failed to get stats: ${error}`);
      return null;
    }
  }

  /**
   * Close database connection
   */
  close(): void {
    try {
      this.db.close();
      logger.info('Chat history database closed');
    } catch (error) {
      logger.error(`Failed to close database: ${error}`);
    }
  }
}
