import { AlertTriangle } from "lucide-react";
import { MarkdownMessage } from "./MarkdownMessage";
import { isErrorMessage } from "./messageUtils";

export interface Msg {
  role: "user" | "assistant";
  content: string;
  error?: boolean;
}

function summarize(content: string): string {
  const firstLine = content.split("\n")[0].trim();
  return firstLine.length > 200 ? firstLine.slice(0, 200) + "…" : firstLine;
}

export function MessageBubble({ msg }: { msg: Msg }) {
  if (isErrorMessage(msg)) {
    return (
      <div className="max-w-[75%] min-w-0 flex items-start gap-2 rounded-xl border border-red-500/50 bg-red-950/30 px-4 py-3">
        <AlertTriangle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
        <p className="text-sm text-red-300 min-w-0 break-words">{summarize(msg.content)}</p>
      </div>
    );
  }

  const isUser = msg.role === "user";
  return (
    <div
      className={`max-w-[75%] min-w-0 px-4 py-2.5 text-sm ${
        isUser
          ? "ml-auto rounded-2xl rounded-br-sm bg-blue-600 text-white"
          : "rounded-2xl rounded-bl-sm bg-slate-800 text-slate-100"
      }`}
    >
      {isUser ? (
        <p className="whitespace-pre-wrap break-words">{msg.content}</p>
      ) : (
        <MarkdownMessage content={msg.content} />
      )}
    </div>
  );
}
