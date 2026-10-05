/**
 * The four calls, and how they fail.
 *
 * The failures are the interesting half. This app is built to run with no server at all, so "the
 * server is not there" is a *mode* rather than an error — and the mode has to come with a reason a
 * reader can act on. A probe that reported only `read-only` would leave them looking for a setting
 * in the app instead of a flag on the command that started the server.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { health, overlay, recordAnnotation, writePermission } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/** Answer every request with one JSON body and status. */
function answers(body: unknown, status = 200) {
  const fetchMock = vi.fn(async () => {
    const text = body === undefined ? "" : JSON.stringify(body);
    return new Response(text, { status, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function refuses() {
  const fetchMock = vi.fn(async () => {
    throw new TypeError("Failed to fetch");
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("probing for a server", () => {
  it("names the provider when one answers", async () => {
    answers({ provider: "mempool.space" });
    expect(await health()).toEqual({ provider: "mempool.space" });
  });

  it("answers null rather than throwing when none does", async () => {
    refuses();
    expect(await health()).toBeNull();
  });

  it("answers null for a server that answers with an error", async () => {
    answers({ error: "nope" }, 500);
    expect(await health()).toBeNull();
  });
});

describe("whether a record can be written", () => {
  it("says why not when the server was started without a directory", async () => {
    answers({ annotations: [], writable: false });
    const permission = await writePermission();
    expect(permission.writable).toBe(false);
    // The flag that would change it, not a generic refusal.
    expect(permission.reason).toMatch(/--annotations/);
  });

  it("says the app is static when nothing is answering", async () => {
    refuses();
    const permission = await writePermission();
    expect(permission.writable).toBe(false);
    expect(permission.reason).toMatch(/static export/);
  });

  it("allows writing when the server says it will write", async () => {
    answers({ annotations: [], writable: true });
    expect(await writePermission()).toEqual({ writable: true, reason: null });
  });
});

describe("sending one assertion", () => {
  const request = {
    target: { kind: "node" as const, key: "address:bitcoin:x", exists: null, note: null },
    kind: "note" as const,
    assertion: "something",
    author: "pm",
    basis: "because",
    evidence_urls: [],
  };

  it("returns the record the server composed", async () => {
    answers({ id: "annotation:abc", created_at: "2026-10-05T00:00:00Z" }, 201);
    const result = await recordAnnotation(request);
    expect(result).toEqual({
      ok: true,
      recorded: { id: "annotation:abc", created_at: "2026-10-05T00:00:00Z" },
    });
  });

  it("passes the server's refusal through in the server's own words", async () => {
    answers({ error: "an annotation must state the basis it rests on" }, 400);
    const result = await recordAnnotation(request);
    expect(result).toEqual({
      ok: false,
      error: "an annotation must state the basis it rests on",
    });
  });

  it("does not mistake an unreadable success for a record", async () => {
    // A 201 whose body is not a record would otherwise be reported as recorded, which is the
    // worst possible outcome: the file may or may not exist and the reader was told it does.
    answers({}, 201);
    const result = await recordAnnotation(request);
    expect(result.ok).toBe(false);
  });

  it("reports a status when the body is not the error shape", async () => {
    answers("<html>nope</html>", 502);
    const result = await recordAnnotation(request);
    expect(result).toEqual({ ok: false, error: "the server answered 502" });
  });
});

describe("reading the join", () => {
  it("returns whatever the server joined", async () => {
    answers({ by_node: {}, unjoined: [] });
    expect(await overlay()).toEqual({ by_node: {}, unjoined: [] });
  });

  it("answers null when the route is not there", async () => {
    answers({ error: "no route for /api/overlay" }, 404);
    expect(await overlay()).toBeNull();
  });
});
