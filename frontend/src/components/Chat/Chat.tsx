import { MessageList } from "./MessageList";
import { PromptInput } from "./PromptInput";

export function Chat() {
  return (
    <section className="chat">
      <MessageList />
      <PromptInput />
    </section>
  );
}
