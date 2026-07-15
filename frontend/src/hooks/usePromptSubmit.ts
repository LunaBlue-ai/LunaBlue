/**
 * Submit a prompt through the API client and drive the chat state machine:
 * pending user message → assistant reply on success, inline error on failure.
 */

import { useCallback } from "react";
import { ApiError, submitPrompt } from "../api/client";
import { useAppDispatch, useAppState } from "../state/AppState";

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  return "Something went wrong submitting the prompt.";
}

export function usePromptSubmit() {
  const { sessionId, messages } = useAppState();
  const dispatch = useAppDispatch();

  const pending = messages.some((message) => message.status === "pending");

  const submit = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) {
        return;
      }
      const messageId = crypto.randomUUID();
      dispatch({ type: "prompt_submitted", messageId, text: trimmed });
      try {
        const response = await submitPrompt({
          text: trimmed,
          session_id: sessionId,
        });
        dispatch({
          type: "prompt_completed",
          messageId,
          requestId: response.request_id,
          sessionId: response.session_id,
          responseText: response.response_text,
          responseStatus: response.status,
        });
      } catch (error) {
        dispatch({ type: "prompt_failed", messageId, error: errorMessage(error) });
        // Only a network failure means the backend is down; an HTTP or
        // validation error proves it answered.
        dispatch({
          type: "connectivity_changed",
          connectivity:
            error instanceof ApiError && error.kind === "network"
              ? "unreachable"
              : "connected",
        });
      }
    },
    [dispatch, sessionId],
  );

  return { submit, pending };
}
