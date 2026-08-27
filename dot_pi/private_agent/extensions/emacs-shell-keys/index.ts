import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { type Component, isKeyRelease, matchesKey } from "@earendil-works/pi-tui";

const WIDGET_KEY = "emacs-shell-keys:input-hook";

/** Keep Ctrl+B as cursor-left without changing pi-interactive-shell's files. */
export default function emacsShellKeys(pi: ExtensionAPI) {
	let removeWidget: (() => void) | undefined;

	const cleanup = () => {
		removeWidget?.();
		removeWidget = undefined;
	};

	pi.on("session_start", (_event, ctx) => {
		cleanup();
		if (ctx.mode !== "tui") return;

		// An empty below-editor widget obtains Pi's live TUI reference without
		// replacing the editor/footer, taking focus, or adding a visible row.
		ctx.ui.setWidget(WIDGET_KEY, (tui) => {
			// Present on Pi 0.85.1's renderer, but not declared on the public TUI
			// interface. If unavailable in another version, leave input alone.
			const focusTui = tui as typeof tui & {
				getFocusedComponent?: () => Component | null;
			};
			const unsubscribe = ctx.ui.onTerminalInput((data) => {
				if (!matchesKey(data, "ctrl+b")) return;

				const focused = focusTui.getFocusedComponent?.();
				const name = focused?.constructor?.name;
				if (name !== "InteractiveShellOverlay" && name !== "ReattachOverlay") return;

				// Compatibility boundary: these names/states belong to
				// pi-interactive-shell 0.15.2, not a public overlay-type API.
				// Inspect only; do not import, patch, or replace its handlers.
				const state = (focused as { state?: string }).state;
				if (state !== "running" && state !== "hands-free") return;

				// Never turn Kitty key-up into another cursor movement. Repeats
				// deliberately translate just like ordinary key presses.
				if (isKeyRelease(data)) return { consume: true };

				// Left Arrow bypasses the overlay's hard-coded Ctrl+B shortcut.
				// Its normal handler still performs hands-free takeover and PTY I/O.
				return { data: "\x1b[D" };
			});

			return {
				render: () => [],
				invalidate() {},
				dispose: unsubscribe,
			};
		}, { placement: "belowEditor" });
		removeWidget = () => ctx.ui.setWidget(WIDGET_KEY, undefined);
	});

	pi.on("session_shutdown", cleanup);
}
