import { useEffect, useState } from "react";
import { resetChatSummary } from "../../api/client";
import { useAppState } from "../../state/AppState";

type ClearState = "idle" | "busy" | "cleared" | "failed";

const LABELS: Record<ClearState, string> = {
  idle: "Clear chat summary",
  busy: "Clearing…",
  cleared: "Cleared ✓",
  failed: "Clear failed — retry",
};

/** How long the "Cleared ✓" confirmation stays before reverting. */
const CONFIRM_MS = 1500;

/**
 * Clears the assistant's internal rolling summary of this conversation
 * (Step 20). The pinned identity fields are unaffected — the backend keeps
 * them outside the cleared buffer.
 */
export function ClearSummaryButton() {
  const { sessionId } = useAppState();
  const [state, setState] = useState<ClearState>("idle");

  useEffect(() => {
    if (state !== "cleared") {
      return undefined;
    }
    const timer = window.setTimeout(() => setState("idle"), CONFIRM_MS);
    return () => window.clearTimeout(timer);
  }, [state]);

  const clear = () => {
    setState("busy");
    resetChatSummary(sessionId)
      .then(() => setState("cleared"))
      .catch(() => setState("failed"));
  };

  return (
    <button
      type="button"
      className="chat-clear-summary"
      disabled={state === "busy"}
      onClick={clear}
      title="Clears the assistant's internal memory of this conversation"
    >
      {LABELS[state]}
    </button>
  );
}
