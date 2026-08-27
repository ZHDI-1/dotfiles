import { spawn } from "node:child_process";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  fetchUsage,
  isUsageResponse,
  type UsageData,
} from "../../npm/node_modules/pi-ollama-cloud/usage.ts";
import { getCloudApiKey } from "../../npm/node_modules/pi-ollama-cloud/utils.ts";

const CODEX_STATUS_KEY = "dual-provider-codex-usage";
const OLLAMA_STATUS_KEY = "dual-provider-ollama-usage";
const REFRESH_INTERVAL_MS = 5 * 60_000;
const REQUEST_TIMEOUT_MS = 20_000;
const MAX_RESPONSE_BYTES = 256 * 1024;
const CODEX_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage";
const OLLAMA_USAGE_URL = "https://ollama.com/api/usage";
const OPENAI_AUTH_CLAIM = "https://api.openai.com/auth";

type RecordValue = Record<string, unknown>;

type UsageWindow = {
  label: string;
  usedPercent: number;
  durationSeconds: number;
  resetAtSeconds?: number;
};

type ProviderState = {
  status: string;
  detail: string;
  updatedAt?: number;
  lastFailureAt?: number;
};

function isRecord(value: unknown): value is RecordValue {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function clampPercent(value: number): number {
  return Math.min(100, Math.max(0, Math.round(value)));
}

function hasProxyEnvironment(): boolean {
  return ["HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"].some(
    (name) => typeof process.env[name] === "string" && process.env[name]!.trim().length > 0,
  );
}

function curlConfigQuote(value: string): string {
  if (value.includes("\r") || value.includes("\n")) {
    throw new Error("Invalid request value");
  }
  return `"${value.replaceAll("\\", "\\\\").replaceAll('"', '\\"')}"`;
}

/**
 * Use curl's stdin config so credentials never appear in argv, files, output,
 * or logs. curl also honors this workstation's HTTP(S)_PROXY/NO_PROXY setup.
 */
async function fetchJsonViaCurl(
  url: string,
  headers: Record<string, string>,
  signal?: AbortSignal,
): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const marker = "__PI_DUAL_USAGE_HTTP_STATUS__:";
    const child = spawn("curl", ["--config", "-"], {
      stdio: ["pipe", "pipe", "pipe"],
    });

    let settled = false;
    let outputBytes = 0;
    const output: Buffer[] = [];

    const finish = (error?: Error, value?: unknown) => {
      if (settled) return;
      settled = true;
      signal?.removeEventListener("abort", onAbort);
      if (error) reject(error);
      else resolve(value);
    };

    const onAbort = () => {
      child.kill("SIGKILL");
      finish(new Error("Usage request aborted"));
    };

    if (signal?.aborted) {
      onAbort();
      return;
    }
    signal?.addEventListener("abort", onAbort, { once: true });

    child.on("error", () => finish(new Error("Usage request transport unavailable")));
    child.stdin.on("error", () => {
      // The child close/error handler owns the final sanitized error.
    });
    child.stderr.resume();
    child.stdout.on("data", (chunk: Buffer) => {
      outputBytes += chunk.length;
      if (outputBytes > MAX_RESPONSE_BYTES) {
        child.kill("SIGKILL");
        finish(new Error("Usage response exceeded the safety limit"));
        return;
      }
      output.push(chunk);
    });

    child.on("close", (code) => {
      if (settled) return;
      if (code !== 0) {
        finish(new Error("Usage request failed"));
        return;
      }

      const raw = Buffer.concat(output).toString("utf8");
      const markerIndex = raw.lastIndexOf(`\n${marker}`);
      if (markerIndex < 0) {
        finish(new Error("Usage response had no HTTP status"));
        return;
      }

      const body = raw.slice(0, markerIndex);
      const status = Number(raw.slice(markerIndex + marker.length + 1).trim());
      if (!Number.isInteger(status) || status < 200 || status >= 300) {
        finish(new Error("Usage endpoint returned an error"));
        return;
      }

      try {
        finish(undefined, JSON.parse(body));
      } catch {
        finish(new Error("Usage endpoint returned invalid JSON"));
      }
    });

    const config = [
      "silent",
      "show-error",
      "request = \"GET\"",
      `connect-timeout = ${Math.ceil(REQUEST_TIMEOUT_MS / 2000)}`,
      `max-time = ${Math.ceil(REQUEST_TIMEOUT_MS / 1000)}`,
      `url = ${curlConfigQuote(url)}`,
      ...Object.entries(headers).map(
        ([name, value]) => `header = ${curlConfigQuote(`${name}: ${value}`)}`,
      ),
      `write-out = "\\n${marker}%{http_code}"`,
    ].join("\n");

    child.stdin.end(`${config}\n`);
  });
}

async function fetchJsonDirect(
  url: string,
  headers: Record<string, string>,
  externalSignal?: AbortSignal,
): Promise<unknown> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  const onAbort = () => controller.abort();
  externalSignal?.addEventListener("abort", onAbort, { once: true });

  try {
    const response = await fetch(url, {
      method: "GET",
      headers,
      signal: controller.signal,
    });
    if (!response.ok) throw new Error("Usage endpoint returned an error");
    const body = await response.text();
    if (Buffer.byteLength(body) > MAX_RESPONSE_BYTES) {
      throw new Error("Usage response exceeded the safety limit");
    }
    return JSON.parse(body);
  } finally {
    clearTimeout(timeout);
    externalSignal?.removeEventListener("abort", onAbort);
  }
}

async function fetchJson(
  url: string,
  headers: Record<string, string>,
  signal?: AbortSignal,
): Promise<unknown> {
  return hasProxyEnvironment()
    ? fetchJsonViaCurl(url, headers, signal)
    : fetchJsonDirect(url, headers, signal);
}

function decodeCodexAccountId(accessToken: string): string {
  const parts = accessToken.split(".");
  if (parts.length !== 3) throw new Error("Codex OAuth token is not a JWT");

  let payload: unknown;
  try {
    payload = JSON.parse(Buffer.from(parts[1]!, "base64url").toString("utf8"));
  } catch {
    throw new Error("Codex OAuth token could not be decoded");
  }

  const authClaim = isRecord(payload) ? payload[OPENAI_AUTH_CLAIM] : undefined;
  const accountId = isRecord(authClaim) ? authClaim.chatgpt_account_id : undefined;
  if (typeof accountId !== "string" || accountId.length === 0) {
    throw new Error("Codex OAuth account ID is unavailable");
  }
  return accountId;
}

function windowLabel(durationSeconds: number): string {
  if (durationSeconds === 18_000) return "5h";
  if (durationSeconds === 604_800) return "7d";
  if (durationSeconds % 86_400 === 0) return `${durationSeconds / 86_400}d`;
  if (durationSeconds % 3600 === 0) return `${durationSeconds / 3600}h`;
  return `${Math.round(durationSeconds / 60)}m`;
}

function parseCodexWindow(value: unknown): UsageWindow | null {
  if (!isRecord(value)) return null;

  const usedPercent = value.used_percent;
  const durationSeconds =
    typeof value.limit_window_seconds === "number"
      ? value.limit_window_seconds
      : typeof value.window_duration_mins === "number"
        ? value.window_duration_mins * 60
        : undefined;

  if (
    typeof usedPercent !== "number" ||
    !Number.isFinite(usedPercent) ||
    typeof durationSeconds !== "number" ||
    !Number.isFinite(durationSeconds) ||
    durationSeconds <= 0
  ) {
    return null;
  }

  const resetAtSeconds =
    typeof value.reset_at === "number" && Number.isFinite(value.reset_at)
      ? value.reset_at
      : undefined;

  return {
    label: windowLabel(durationSeconds),
    usedPercent: clampPercent(usedPercent),
    durationSeconds,
    ...(resetAtSeconds !== undefined ? { resetAtSeconds } : {}),
  };
}

function parseCodexUsage(data: unknown): UsageWindow[] {
  if (!isRecord(data) || !isRecord(data.rate_limit)) {
    throw new Error("Codex usage response shape changed");
  }

  const windows = [
    parseCodexWindow(data.rate_limit.primary_window),
    parseCodexWindow(data.rate_limit.secondary_window),
  ]
    .filter((window): window is UsageWindow => window !== null)
    .sort((a, b) => a.durationSeconds - b.durationSeconds);

  if (windows.length === 0) throw new Error("Codex usage windows are unavailable");
  return windows;
}

function formatReset(resetAtSeconds?: number): string {
  return resetAtSeconds === undefined
    ? "reset time unavailable"
    : `resets ${new Date(resetAtSeconds * 1000).toISOString()}`;
}

function codexStateFromWindows(windows: UsageWindow[]): ProviderState {
  return {
    status: windows.map((window) => `${window.label}:${window.usedPercent}%`).join(" "),
    detail: `Codex: ${windows
      .map(
        (window) =>
          `${window.label} ${window.usedPercent}% used (${formatReset(window.resetAtSeconds)})`,
      )
      .join("; ")}`,
    updatedAt: Date.now(),
  };
}

function ollamaPercent(value: number): number {
  return clampPercent(value * 100);
}

function ollamaStateFromUsage(data: UsageData): ProviderState {
  const session = ollamaPercent(data.limits.session.usage);
  const weekly = ollamaPercent(data.limits.weekly.usage);
  return {
    status: `5h:${session}% 7d:${weekly}%`,
    detail: `Ollama: 5h ${session}% used; 7d ${weekly}% used (exact reset times are not exposed)`,
    updatedAt: Date.now(),
  };
}

async function loadCodexState(
  ctx: Pick<ExtensionContext, "modelRegistry">,
  signal?: AbortSignal,
): Promise<ProviderState> {
  const auth = await ctx.modelRegistry.getProviderAuth("openai-codex");
  const accessToken = auth?.auth.apiKey;
  if (!accessToken) throw new Error("Codex OAuth is unavailable");

  const accountId = decodeCodexAccountId(accessToken);
  const data = await fetchJson(
    CODEX_USAGE_URL,
    {
      Authorization: `Bearer ${accessToken}`,
      "chatgpt-account-id": accountId,
      originator: "pi",
    },
    signal,
  );
  return codexStateFromWindows(parseCodexUsage(data));
}

async function loadOllamaState(
  ctx: Pick<ExtensionContext, "modelRegistry">,
  signal?: AbortSignal,
): Promise<ProviderState> {
  const apiKey = await getCloudApiKey(ctx);
  if (!apiKey) throw new Error("Ollama Cloud credential is unavailable");

  if (!hasProxyEnvironment()) {
    return ollamaStateFromUsage(await fetchUsage(apiKey, signal));
  }

  const data = await fetchJsonViaCurl(
    OLLAMA_USAGE_URL,
    { Authorization: `Bearer ${apiKey}` },
    signal,
  );
  if (!isUsageResponse(data)) throw new Error("Ollama usage response shape changed");
  return ollamaStateFromUsage(data);
}

function formatUpdatedAt(timestamp?: number): string {
  return timestamp === undefined ? "never loaded" : `updated ${new Date(timestamp).toISOString()}`;
}

export default function dualProviderUsage(pi: ExtensionAPI) {
  let codexState: ProviderState = { status: "?", detail: "Codex: unavailable" };
  let ollamaState: ProviderState = { status: "?", detail: "Ollama: unavailable" };
  let refreshTimer: ReturnType<typeof setInterval> | undefined;
  let refreshAbort: AbortController | undefined;
  let refreshInFlight: Promise<void> | undefined;
  let lastRefreshAttempt = 0;

  function publish(ctx: ExtensionContext) {
    if (ctx.mode !== "tui") return;
    ctx.ui.setStatus(CODEX_STATUS_KEY, codexState.status);
    ctx.ui.setStatus(OLLAMA_STATUS_KEY, ollamaState.status);
  }

  async function refresh(ctx: ExtensionContext, force = false): Promise<void> {
    if (refreshInFlight) return refreshInFlight;
    if (!force && Date.now() - lastRefreshAttempt < REFRESH_INTERVAL_MS) return;

    lastRefreshAttempt = Date.now();
    refreshAbort = new AbortController();
    const signal = refreshAbort.signal;

    refreshInFlight = (async () => {
      const [codexResult, ollamaResult] = await Promise.allSettled([
        loadCodexState(ctx, signal),
        loadOllamaState(ctx, signal),
      ]);

      if (codexResult.status === "fulfilled") {
        codexState = codexResult.value;
      } else {
        codexState = { ...codexState, lastFailureAt: Date.now() };
      }

      if (ollamaResult.status === "fulfilled") {
        ollamaState = ollamaResult.value;
      } else {
        ollamaState = { ...ollamaState, lastFailureAt: Date.now() };
      }

      publish(ctx);
    })().finally(() => {
      refreshAbort = undefined;
      refreshInFlight = undefined;
    });

    return refreshInFlight;
  }

  pi.on("session_start", async (_event, ctx) => {
    if (ctx.mode !== "tui") return;
    publish(ctx);
    void refresh(ctx, true);
    refreshTimer = setInterval(() => void refresh(ctx), REFRESH_INTERVAL_MS);
    refreshTimer.unref?.();
  });

  pi.on("agent_end", async (_event, ctx) => {
    if (ctx.mode === "tui") await refresh(ctx);
  });

  pi.on("session_shutdown", async (_event, ctx) => {
    if (refreshTimer) clearInterval(refreshTimer);
    refreshTimer = undefined;
    refreshAbort?.abort();
    ctx.ui.setStatus(CODEX_STATUS_KEY, undefined);
    ctx.ui.setStatus(OLLAMA_STATUS_KEY, undefined);
  });

  pi.registerCommand("dual-usage", {
    description: "Show Codex and Ollama usage/reset details; use /dual-usage refresh to refresh now.",
    handler: async (args, ctx) => {
      const action = args.trim().toLowerCase();
      if (action && action !== "refresh") {
        ctx.ui.notify("Usage: /dual-usage [refresh]", "warning");
        return;
      }
      if (action === "refresh") await refresh(ctx, true);

      const lines = [
        `${codexState.detail}; ${formatUpdatedAt(codexState.updatedAt)}`,
        `${ollamaState.detail}; ${formatUpdatedAt(ollamaState.updatedAt)}`,
      ];
      if (codexState.lastFailureAt && codexState.updatedAt) {
        lines.push("Codex: last refresh failed; showing the last successful value.");
      }
      if (ollamaState.lastFailureAt && ollamaState.updatedAt) {
        lines.push("Ollama: last refresh failed; showing the last successful value.");
      }
      ctx.ui.notify(lines.join("\n"), "info");
    },
  });
}
