import type { AssistantMessage, TextContent, UserMessage } from "@earendil-works/pi-ai";
import type { SessionEntry } from "@earendil-works/pi-coding-agent";

export type TurnStatus = "complete" | "waiting" | "incomplete" | "aborted" | "error" | "truncated";
export interface CleanTurn {
  id: string;
  prompt: string;
  reply?: string;
  replyId?: string;
  replyKind: "completed" | "partial" | "previous" | "none";
  status: TurnStatus;
  hiddenReplies: number;
}

interface Reply {
  id: string;
  text: string;
}
interface PendingTurn {
  id: string;
  prompt: string;
  lastAssistant?: { id: string; message: AssistantMessage };
  completed?: Reply;
  lastText?: Reply;
  textReplies: number;
}

/** Signatures can also be opaque IDs from older sessions or other providers. */
export function textPhase(block: TextContent): "commentary" | "final_answer" | undefined {
  if (typeof block.textSignature !== "string" || !block.textSignature.startsWith("{")) return;
  try {
    const signature = JSON.parse(block.textSignature);
    if (signature?.v === 1 && (signature.phase === "commentary" || signature.phase === "final_answer")) {
      return signature.phase;
    }
  } catch {
    // Missing/malformed metadata is not a reason to drop otherwise readable text.
  }
}

function assistantText(message: AssistantMessage, includeCommentary: boolean): string {
  return message.content
    .filter((block): block is TextContent => block.type === "text" && Boolean(block.text.trim()))
    .filter((block) => includeCommentary || textPhase(block) !== "commentary")
    .map((block) => block.text)
    .join("\n\n");
}

function promptText(message: UserMessage): string {
  if (typeof message.content === "string") return message.content || "[Empty user message]";
  const text = message.content.filter((block) => block.type === "text").map((block) => block.text).join("\n\n");
  const images = message.content.filter((block) => block.type === "image").length;
  return [text, images ? `[${images} image${images === 1 ? "" : "s"} attached]` : ""].filter(Boolean).join("\n\n") || "[Empty user message]";
}

function finish(turn: PendingTurn): CleanTurn {
  const result: CleanTurn = {
    id: turn.id, prompt: turn.prompt, replyKind: "none", status: "waiting", hiddenReplies: 0,
  };
  const last = turn.lastAssistant;
  if (!last) return result;
  const stop = last.message.stopReason;
  const hasTools = last.message.content.some((block) => block.type === "toolCall");
  const failed = stop === "error" || stop === "aborted" || stop === "length";
  result.status = stop === "error" ? "error" : stop === "aborted" ? "aborted" : stop === "length" ? "truncated" : "incomplete";

  let selected: Reply | undefined;
  if (failed) {
    // Never silently present an older successful answer as the failed attempt's answer.
    const partial = assistantText(last.message, true);
    selected = partial ? { id: last.id, text: partial } : turn.completed ?? turn.lastText;
    result.replyKind = partial ? "partial" : selected ? "previous" : "none";
  } else if (!hasTools && turn.completed?.id === last.id) {
    selected = turn.completed;
    result.status = "complete";
    result.replyKind = "completed";
  } else {
    selected = turn.completed ?? turn.lastText;
    result.replyKind = selected ? (turn.completed ? "previous" : "partial") : "none";
  }
  if (selected) {
    result.reply = selected.text;
    result.replyId = selected.id;
  }
  result.hiddenReplies = Math.max(0, turn.textReplies - (selected ? 1 : 0));
  return result;
}

/**
 * Read-only projection of getBranch(), NOT getEntries()/buildSessionContext().
 * The next persisted user message closes a group. Custom notifications, tools,
 * summaries, settings and model switches never create prompt boundaries.
 */
export function buildCleanTurns(branch: readonly SessionEntry[]): CleanTurn[] {
  const turns: CleanTurn[] = [];
  let current: PendingTurn | undefined;
  for (const entry of branch) {
    if (entry.type !== "message") continue;
    const message = entry.message;
    if (message.role === "user") {
      if (current) turns.push(finish(current));
      current = { id: entry.id, prompt: promptText(message), textReplies: 0 };
    } else if (message.role === "assistant" && current) {
      current.lastAssistant = { id: entry.id, message };
      const text = assistantText(message, true);
      if (text) {
        current.lastText = { id: entry.id, text };
        current.textReplies++;
      }
      const clean = assistantText(message, false);
      // No provider allowlist: explicit phases refine text; untagged K3/other
      // providers use the same normal-completion/no-tool boundary. Missing stop
      // reasons are tolerated only for old complete, non-tool session messages.
      if (clean && (message.stopReason === "stop" || message.stopReason === undefined) &&
          !message.content.some((block) => block.type === "toolCall")) {
        current.completed = { id: entry.id, text: clean };
      }
    }
  }
  if (current) turns.push(finish(current));
  return turns;
}

export function statusText(turn: CleanTurn): string {
  const status: Record<TurnStatus, string> = {
    complete: "", waiting: "No assistant reply recorded.",
    incomplete: "No completed reply at this point.",
    aborted: "Latest response was interrupted.", error: "Latest response failed.",
    truncated: "Latest response was truncated.",
  };
  return status[turn.status];
}
