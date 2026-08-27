# Emacs shell keys (local override)

Rewrites **Ctrl+B to Left Arrow** only when a running `pi-interactive-shell`
overlay has keyboard focus, including reattached and hands-free sessions.
Pi's prompt editor, other dialogs, Ctrl+Shift+B, and other keys are untouched.
Backgrounding is still available through the shell overlay's **Ctrl+Q menu**.

No installed package files or runtime methods are patched. A zero-row widget
obtains Pi's live TUI reference; `onTerminalInput` rewrites the key before the
overlay's hard-coded shortcut sees it. The input listener is removed on widget
disposal/session shutdown. No extra tools, commands, or shortcuts are registered.

## Activate / remove

This directory is auto-discovered from `~/.pi/agent/extensions/`. Run `/reload`
when no shell session needs preserving (interactive-shell kills its sessions on
reload), or restart Pi. To remove, move this directory outside `extensions/` and
reload/restart. Your separate `keybindings.json` settings are not affected.

## Separate Pi navigation settings

`~/.pi/agent/keybindings.json` also configures:

- **Ctrl+N / Ctrl+P**: next / previous item in Pi menus and completion lists.
  Down / Up arrows still work.
- In the prompt editor without an open completion list, Ctrl+N / Ctrl+P retain
  next / previous prompt-history navigation.
- In `/resume`: **Alt+N** toggles the named-session filter; **Alt+P** toggles paths.
- In `/scoped-models`: **Ctrl+Alt+P** toggles the selected provider's models.
  Plain Alt+P is already Pi's legacy alias for Alt+Up (reorder model up).

These are ordinary Pi settings, not terminal-input rewrites. They apply to
components using Pi's shared keybindings; third-party menus with hard-coded
arrow handlers may need separate support. They do not rewrite input sent to a
shell subprocess. Apply with `/reload` or restart as described above.

## Compatibility and limitations

- Written against Pi 0.85.1 and `pi-interactive-shell` 0.15.2.
- Uses the renderer's runtime `getFocusedComponent()` method (not declared on
  Pi's public `TUI` interface). If absent, it leaves input untouched.
- Recognizes the focused component by the package's class names
  (`InteractiveShellOverlay`, `ReattachOverlay`) and states (`running`,
  `hands-free`). These are implementation details, so rerun tests after upgrades.
  Unrecognized components/states are left alone.
- Sends Left Arrow, **not literal Ctrl+B**, to the subprocess. This provides
  cursor-left in normal Readline/Emacs-style editing, but applications with
  different arrow bindings may behave differently.
- The unmodified package may still display **Ctrl+B background** hints. Those
  hints are not rewritten; use Ctrl+Q instead.
- Kitty press/repeat events move left; release events do not.

## Regression tests

```sh
node --test ~/.pi/agent/extensions/emacs-shell-keys/tests/verify.mjs
```

Tests use the installed Pi loader, real TUI input routing, original overlay
handlers with fake PTYs, and Pi/Powerline editors. They do not reload your live
session, launch agents, or start a shell. Test paths target this workstation's
installed Pi and the saved originals in its cache.
