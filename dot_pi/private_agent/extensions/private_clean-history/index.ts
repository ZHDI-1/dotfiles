import type { ExtensionAPI, ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import { buildCleanTurns } from "./model.ts";
import { CleanHistoryView } from "./view.ts";

/** UI-only: no tools, model/context hooks, persistence, network, or settings. */
export default function cleanHistory(pi: ExtensionAPI): void {
  type ActiveView = { view: CleanHistoryView; ctx: ExtensionCommandContext; close: () => void };
  let active: ActiveView | undefined;
  let refreshTimer: ReturnType<typeof setTimeout> | undefined;

  const cancelRefresh = () => {
    if (refreshTimer !== undefined) clearTimeout(refreshTimer);
    refreshTimer = undefined;
  };
  const close = () => {
    cancelRefresh();
    const previous = active;
    active = undefined;
    previous?.close();
  };
  const scheduleRefresh = () => {
    if (!active || refreshTimer !== undefined) return;
    // Coalesce safe lifecycle events, not token deltas. A timer is NOT a
    // persistence barrier: message_end handlers can still be awaiting other
    // extensions. Completed messages are read after turn_end instead.
    refreshTimer = setTimeout(() => {
      refreshTimer = undefined;
      const current = active;
      if (!current) return;
      try {
        current.view.update(buildCleanTurns(current.ctx.sessionManager.getBranch()), !current.ctx.isIdle());
      } catch {
        close();
        current.ctx.ui.notify("Clean history could not refresh; returned to the full chat.", "error");
      }
    }, 0);
  };

  pi.registerCommand("answers", {
    description: "Clean history: each user prompt and its latest reply; q/Esc returns to full chat",
    handler: async (args, ctx) => {
      if (ctx.mode !== "tui") {
        if (ctx.hasUI) ctx.ui.notify("/answers is an interactive Pi viewer; it is not available over RPC.", "warning");
        return;
      }
      if (args.trim()) {
        ctx.ui.notify("Usage: /answers — opens the active branch's clean history.", "info");
        return;
      }
      if (active) {
        close();
        return;
      }
      let owned: ActiveView | undefined;
      try {
        await ctx.ui.custom<void>((tui, theme, _keybindings, done) => {
          const view = new CleanHistoryView(tui, theme, () => done());
          owned = { view, ctx, close: () => done() };
          active = owned;
          view.update(buildCleanTurns(ctx.sessionManager.getBranch()), !ctx.isIdle());
          return view;
        }, {
          overlay: true,
          overlayOptions: { width: "100%", maxHeight: "100%", anchor: "top-left", margin: 0 },
        });
      } finally {
        if (active === owned) {
          active = undefined;
          cancelRefresh();
        }
      }
    },
  });

  pi.on("message_start", (event) => {
    // The previous user message is persisted before the assistant starts.
    if (event.message.role === "assistant") scheduleRefresh();
  });
  pi.on("turn_end", scheduleRefresh);
  pi.on("agent_end", scheduleRefresh);
  pi.on("agent_settled", scheduleRefresh);
  pi.on("session_tree", scheduleRefresh);
  pi.on("session_compact", scheduleRefresh);
  pi.on("session_shutdown", close);
}
