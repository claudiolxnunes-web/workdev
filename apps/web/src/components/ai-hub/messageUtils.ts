import type { Msg } from "./MessageBubble";

const ERROR_PREFIX_RE = /^Erro (ao|na|no)\b/i;

export function isErrorMessage(m: Msg): boolean {
  return m.role === "assistant" && (!!m.error || ERROR_PREFIX_RE.test(m.content.trim()));
}
