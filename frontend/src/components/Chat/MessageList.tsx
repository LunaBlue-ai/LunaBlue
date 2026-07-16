import { useEffect, useRef } from "react";
import { useAppState } from "../../state/AppState";

/** Friendly labels for the run phases streamed while a prompt is pending. */
const PHASE_LABELS: Record<string, string> = {
  received: "Queued",
  governance: "Checking governance",
  engineering: "Engineering the prompt",
  reviewing: "Reviewing the draft",
  responding: "Writing the response",
  completed: "Finishing up",
  failed: "Finishing up",
};

export function MessageList() {
  const { messages } = useAppState();
  const bottomRef = useRef<HTMLDivElement>(null);
  const pendingMessage = messages.find(
    (message) => message.role === "user" && message.status === "pending",
  );
  const pending = pendingMessage !== undefined;
  // Live phase from run_updated events (or polls); "Thinking" until known.
  const pendingLabel =
    (pendingMessage?.livePhase && PHASE_LABELS[pendingMessage.livePhase]) ||
    "Thinking";

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, pending, pendingLabel]);

  if (messages.length === 0) {
    return (
      <div className="message-list message-list-empty">
        <p>Ask LunaBlue anything to get started.</p>
      </div>
    );
  }

  return (
    <div className="message-list" role="log" aria-live="polite">
      {messages.map((message) => (
        <div
          key={message.id}
          className={`message message-${message.role} message-${message.status}`}
        >
          <span className="message-author">
            {message.role === "user" ? "You" : "LunaBlue"}
          </span>
          <div className="message-text">{message.text}</div>
          {message.status === "failed" && message.error && (
            <div className="message-error" role="alert">
              {message.error}
            </div>
          )}
        </div>
      ))}
      {pending && (
        <div className="message message-assistant message-pending-indicator">
          <span className="message-author">LunaBlue</span>
          <div className="message-text">
            {pendingLabel}
            <span className="pending-dots" aria-hidden="true" />
          </div>
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  );
}
