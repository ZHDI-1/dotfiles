import { getMarkdownTheme, type Theme } from "@earendil-works/pi-coding-agent";
import {
  Markdown, matchesKey, stripTerminalSequences, truncateToWidth, visibleWidth,
  type Component, type TUI, type TuiMouseEvent, type TuiMouseEventResult,
} from "@earendil-works/pi-tui";
import { statusText, type CleanTurn } from "./model.ts";

/** Do not let historical pasted terminal control sequences drive the terminal. */
export function displayText(text: string): string {
  return stripTerminalSequences(text).replace(/\r\n?/g, "\n").replace(/[\x00-\x08\x0b-\x1f\x7f-\x9f]/g, "");
}

export class CleanHistoryView implements Component {
  private turns: CleanTurn[] = [];
  private running = false;
  private cacheWidth = -1;
  private lines: string[] = [];
  private promptStarts: number[] = [];
  private offset = 0;
  private followBottom = true;
  private bodyHeight = 1;
  private closed = false;

  constructor(private tui: TUI, private theme: Theme, private close: () => void) {}

  update(turns: CleanTurn[], running: boolean): void {
    if (this.closed) return;
    this.turns = turns;
    this.running = running;
    this.invalidate();
    this.tui.requestRender();
  }

  invalidate(): void {
    this.cacheWidth = -1;
  }

  private rebuild(width: number): void {
    if (this.cacheWidth === width) return;
    this.lines = [];
    this.promptStarts = [];
    const markdownTheme = getMarkdownTheme();
    const markdown = (text: string) => new Markdown(displayText(text), width >= 8 ? 1 : 0, 0, markdownTheme).render(width);
    for (const [index, turn] of this.turns.entries()) {
      this.promptStarts.push(this.lines.length);
      this.lines.push(this.theme.fg("accent", this.theme.bold(`User ${index + 1}`)));
      this.lines.push(...markdown(turn.prompt), "");
      const qualifier = turn.replyKind === "partial" ? " (partial)" : turn.replyKind === "previous" ? " (earlier reply)" : "";
      this.lines.push(this.theme.fg("accent", this.theme.bold(`Assistant${qualifier}`)));
      if (turn.reply !== undefined) this.lines.push(...markdown(turn.reply));
      const note = statusText(turn);
      if (note) this.lines.push(this.theme.fg("warning", note));
      if (turn.hiddenReplies) this.lines.push(this.theme.fg("dim", `${turn.hiddenReplies} earlier/intermediate assistant message${turn.hiddenReplies === 1 ? "" : "s"} hidden`));
      this.lines.push("", this.theme.fg("borderMuted", "─".repeat(Math.max(0, width))), "");
    }
    if (!this.turns.length) this.lines.push("No user prompts on the active branch yet.");
    this.cacheWidth = width;
  }

  private maxOffset(): number {
    return Math.max(0, this.lines.length - this.bodyHeight);
  }

  private scrollTo(offset: number): void {
    this.offset = Math.max(0, Math.min(offset, this.maxOffset()));
    this.followBottom = this.offset === this.maxOffset();
    this.tui.requestRender();
  }

  render(width: number): string[] {
    if (width < 1 || this.closed) return [];
    const height = Math.max(1, Math.floor(this.tui.terminal.rows) || 24);
    this.bodyHeight = Math.max(0, height - 2);
    this.rebuild(width);
    this.offset = this.followBottom ? this.maxOffset() : Math.min(this.offset, this.maxOffset());
    const total = this.turns.length;
    const header = this.theme.fg("accent", this.theme.bold(`Clean history · ${total} prompt${total === 1 ? "" : "s"} · active branch`)) +
      (this.running ? this.theme.fg("warning", " · agent working; latest saved replies shown") : "");
    const rows = [header];
    if (height > 1) {
      const body = this.lines.slice(this.offset, this.offset + this.bodyHeight);
      rows.push(...body, ...Array(Math.max(0, this.bodyHeight - body.length)).fill(""));
      const position = `${Math.min(this.offset + 1, this.lines.length)}–${Math.min(this.offset + this.bodyHeight, this.lines.length)}/${this.lines.length}`;
      rows.push(this.theme.fg("dim", `q/Esc/f: full chat · j/k: scroll · d/u: half page · PgUp/PgDn · [/]: prompts · g/G: ends · ${position}`));
    }
    // A full, opaque viewport prevents the underlying noisy chat bleeding through.
    return rows.map((row) => {
      const line = truncateToWidth(row, width, "");
      return line + " ".repeat(Math.max(0, width - visibleWidth(line)));
    });
  }

  handleInput(data: string): void {
    if (this.closed) return;
    if (data === "q" || data === "f" || matchesKey(data, "escape") || matchesKey(data, "ctrl+c")) {
      this.closed = true;
      this.close();
    } else if (data === "j" || matchesKey(data, "down") || matchesKey(data, "ctrl+n")) {
      this.scrollTo(this.offset + 1);
    } else if (data === "k" || matchesKey(data, "up") || matchesKey(data, "ctrl+p")) {
      this.scrollTo(this.offset - 1);
    } else if (data === "d" || matchesKey(data, "ctrl+d")) {
      this.scrollTo(this.offset + Math.max(1, Math.floor(this.bodyHeight / 2)));
    } else if (data === "u" || matchesKey(data, "ctrl+u")) {
      this.scrollTo(this.offset - Math.max(1, Math.floor(this.bodyHeight / 2)));
    } else if (matchesKey(data, "pageDown") || data === " " || matchesKey(data, "ctrl+f")) {
      this.scrollTo(this.offset + Math.max(1, this.bodyHeight - 1));
    } else if (matchesKey(data, "pageUp") || matchesKey(data, "ctrl+b")) {
      this.scrollTo(this.offset - Math.max(1, this.bodyHeight - 1));
    } else if (data === "g" || matchesKey(data, "home")) {
      this.scrollTo(0);
    } else if (data === "G" || matchesKey(data, "end")) {
      this.scrollTo(this.maxOffset());
    } else if (data === "[") {
      this.scrollTo(this.promptStarts.findLast((start) => start < this.offset) ?? 0);
    } else if (data === "]") {
      this.scrollTo(this.promptStarts.find((start) => start > this.offset) ?? this.maxOffset());
    }
  }

  handleMouse(event: TuiMouseEvent): TuiMouseEventResult | undefined {
    if (event.type !== "wheel" || this.closed) return;
    this.scrollTo(this.offset + (event.wheelDelta ?? 0));
    return { handled: true, render: true };
  }

  dispose(): void {
    this.closed = true;
    this.turns = [];
    this.lines = [];
    this.promptStarts = [];
  }
}
