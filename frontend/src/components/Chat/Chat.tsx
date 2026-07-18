import { ClearSummaryButton } from "./ClearSummaryButton";
import { MessageList } from "./MessageList";
import { PromptInput } from "./PromptInput";

export function Chat() {
  return (
    <section className="chat">
      <header className="chat-header">
        <ClearSummaryButton />
      </header>
      <MessageList />
      <PromptInput />
    </section>
  );
}
