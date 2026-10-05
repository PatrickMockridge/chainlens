/**
 * The four calls the app makes to a local server, in one place.
 *
 * Small enough to be a module rather than a client class, and separate from the components
 * because two of the four are about *posture* rather than data: whether a record can be written
 * is the server's answer to give, and the app must show the server's reason rather than its own
 * guess. A component that inline-fetched would end up paraphrasing that reason, and a reader
 * would be told "read-only" without being told how to change it.
 *
 * Every one of these fails by returning a shape rather than by throwing, because the app is built
 * to run with no server at all: a failed probe is a *mode*, not an error.
 */
import type { AnnotationRequest, OverlayDocument } from "./schema/documents";

export interface Health {
  readonly provider: string;
}

/** A refused call, with the server's own wording where it gave any. */
export interface Failure {
  readonly error: string;
}

export function isFailure(value: unknown): value is Failure {
  return typeof value === "object" && value !== null && "error" in value;
}

async function call(
  path: string,
  init: RequestInit = {},
): Promise<{ ok: true; body: unknown } | { ok: false; error: string }> {
  try {
    const response = await fetch(path, init);
    const text = await response.text();
    // The server answers errors with `{"error": "..."}`; anything else that is not ok is reported
    // with its status, because "400" is more useful than "the body was not JSON".
    let parsed: unknown = null;
    try {
      parsed = text === "" ? null : JSON.parse(text);
    } catch {
      parsed = null;
    }
    if (!response.ok) {
      const message = isFailure(parsed)
        ? parsed.error
        : `the server answered ${response.status}`;
      return { ok: false, error: message };
    }
    return { ok: true, body: parsed };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}

export async function health(signal?: AbortSignal): Promise<Health | null> {
  const result = await call("/api/health", { signal });
  if (!result.ok) return null;
  const provider = (result.body as { provider?: unknown } | null)?.provider;
  return { provider: typeof provider === "string" ? provider : "unknown" };
}

/** The graph as the server reads it now, rebuilt from its own walk. */
export async function document(signal?: AbortSignal): Promise<unknown | null> {
  const result = await call("/api/document", { signal });
  return result.ok ? result.body : null;
}

/** Everything known about the graph, joined server-side. Re-read on every call. */
export async function overlay(signal?: AbortSignal): Promise<unknown | null> {
  const result = await call("/api/overlay", { signal });
  return result.ok ? result.body : null;
}

/**
 * Walk one level out from an address, as another document to union.
 *
 * Only an address may be expanded, and that is the server's rule rather than this client's: a
 * transaction node's neighbours are already drawn with it, because the walk draws a transaction
 * whole. Asking for one is refused rather than guessed at, so the refusal is surfaced verbatim.
 */
export async function expand(
  nodeKey: string,
  depth = 1,
  signal?: AbortSignal,
): Promise<{ ok: true; document: unknown } | { ok: false; error: string }> {
  const result = await call("/api/expand", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ node_key: nodeKey, depth }),
    ...(signal ? { signal } : {}),
  });
  return result.ok ? { ok: true, document: result.body } : result;
}

export interface WritePermission {
  /** Whether the server will accept a record, and why not when it will not. */
  readonly writable: boolean;
  readonly reason: string | null;
}

/**
 * Whether a record can be written, and the server's reason when it cannot.
 *
 * The server answers `writable` even with nothing to read, precisely so the app can grey out the
 * annotation form rather than offering to record something and then being refused.
 */
export async function writePermission(signal?: AbortSignal): Promise<WritePermission> {
  const result = await call("/api/annotations", { signal });
  if (!result.ok) {
    return {
      writable: false,
      reason:
        "no server is answering, so this is a static export: it can show what a provider " +
        "recorded, and it cannot record anything",
    };
  }
  const payload = result.body as { writable?: unknown } | null;
  const writable = payload?.writable === true;
  return {
    writable,
    reason: writable
      ? null
      : "the server was started without an annotation directory, so it will not write to disk; " +
        "restart it with --annotations <dir> to record one",
  };
}

export interface Recorded {
  readonly annotation: { id: string; created_at: string };
}

/** Send one assertion. Resolves with the server's own error message when it is refused. */
export async function recordAnnotation(
  request: AnnotationRequest,
): Promise<{ ok: true; recorded: Recorded["annotation"] } | { ok: false; error: string }> {
  const result = await call("/api/annotations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!result.ok) return result;
  const body = result.body as Recorded["annotation"] | null;
  if (body === null || typeof body.id !== "string") {
    return { ok: false, error: "the server accepted the record but returned nothing readable" };
  }
  return { ok: true, recorded: body };
}

export type { OverlayDocument };
