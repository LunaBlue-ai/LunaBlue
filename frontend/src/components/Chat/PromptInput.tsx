import { useState, type FormEvent, type KeyboardEvent } from "react";
import { usePromptSubmit } from "../../hooks/usePromptSubmit";

export function PromptInput() {
  const [text, setText] = useState("");
  const { submit, pending } = usePromptSubmit();

  const send = () => {
    if (pending || !text.trim()) {
      return;
    }
    void submit(text);
    setText("");
  };

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    send();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      send();
    }
  };

  return (
    <form className="prompt-input" onSubmit={onSubmit}>
      <textarea
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={onKeyDown}
        placeholder="Send a prompt (Enter to send, Shift+Enter for a new line)"
        rows={2}
        aria-label="Prompt"
      />
      <button type="submit" disabled={pending || !text.trim()}>
        {pending ? "Waiting…" : "Send"}
      </button>
    </form>
  );
}
