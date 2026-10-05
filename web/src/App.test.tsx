/**
 * The shell: which view is showing, and what it says before anything is loaded.
 *
 * Two views over one store is a claim about the *app*, not about either view, so it is asserted
 * here: the switcher changes which one renders, and neither throws away what the other holds.
 * The probe against `/api/health` fails in jsdom, which is the static case — the mode the app is
 * in when somebody opens a committed export with no server behind it.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DerivationDocument, LedgerDocument } from "./schema/documents";
import { App } from "./App";

const here = dirname(fileURLToPath(import.meta.url));
const fixtures = JSON.parse(
  readFileSync(join(here, "..", "..", "tests", "ledger", "fixtures", "graph-document.json"), "utf8"),
) as {
  ledgers: Record<string, LedgerDocument>;
  overlays: Record<string, unknown>;
  derivations: Record<string, DerivationDocument>;
};

afterEach(() => {
  vi.unstubAllGlobals();
});

/**
 * A server that answers, stubbed at the transport.
 *
 * The live path is where three things the front-end suite otherwise cannot reach live: the header
 * saying which provider answered *and when it walked*, the write permission the server decides,
 * and the overlay being read at boot. A live server walks once at startup, so a header saying only
 * `live` would let an hour-old graph read as a fresh read — which is why the walk time is
 * asserted rather than assumed.
 */
function serving(overrides: Record<string, unknown> = {}) {
  const bodies: Record<string, unknown> = {
    "/api/health": { status: "ok", mode: "live", provider: "in-memory", chain: "bitcoin", writes: false },
    "/api/document": fixtures.ledgers["bitcoin"],
    "/api/annotations": { annotations: [], writable: false },
    "/api/overlay": fixtures.overlays["bitcoin"],
    ...overrides,
  };
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.pathname : input.url;
    const body = bodies[url];
    if (body === undefined) return new Response("{}", { status: 404 });
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
}

/** Drop a document on the app, the way a reader loads a committed export. */
function drop(container: HTMLElement, name: string, document: unknown) {
  const file = { name, text: () => Promise.resolve(JSON.stringify(document)) };
  fireEvent.drop(container.querySelector(".app")!, {
    dataTransfer: { files: [file] },
  });
}

describe("the app shell", () => {
  it("opens in Explore and can be switched to Verify", () => {
    const { container } = render(<App />);
    expect(screen.getByRole("button", { name: "Explore" })).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: /Verify/ }));
    expect(screen.getByRole("button", { name: /Verify/ })).toHaveAttribute("aria-pressed", "true");
    // Verify with nothing loaded says how to get a derivation rather than rendering nothing.
    expect(screen.getByText("No derivation loaded")).toBeInTheDocument();
    void container;
  });

  it("keeps the linkage caveat in both views", () => {
    // The misreading the caveat prevents is available in either view — the Verify pane draws the
    // same graph — so it cannot be dropped when a reader switches.
    const { container } = render(<App />);
    expect(container.querySelector(".caveat")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Verify/ }));
    expect(container.querySelector(".caveat")).not.toBeNull();
  });

  it("counts the derivations in the switcher, so a loaded one is visible from either view", async () => {
    const { container } = render(<App />);
    drop(container, "derivation.json", fixtures.derivations["no_ratio"]);
    // Reading a dropped file is a promise, so the count arrives a microtask later.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Verify \(1\)/ })).toBeInTheDocument(),
    );
  });
});

describe("with a server answering", () => {
  it("says which provider answered and when it walked", async () => {
    serving();
    render(<App />);
    // The graph carries its own `generated_at`, and the server walks once at startup — so the
    // header says when, rather than letting `live` stand in for "a moment ago".
    await waitFor(() => expect(screen.getByText(/live · in-memory · walked/)).toBeInTheDocument());
  });

  it("loads the graph and the join the server serves", async () => {
    serving();
    render(<App />);
    // The +N notice is what a loaded ledger document reports, so the graph arrived.
    await waitFor(() => expect(screen.getByText(/Loaded live:/)).toBeInTheDocument());
  });

  it("stays static, with no walk time, when no server answers", async () => {
    vi.stubGlobal("fetch", async () => {
      throw new TypeError("Failed to fetch");
    });
    render(<App />);
    await waitFor(() => expect(screen.getByText(/static · no server answering/)).toBeInTheDocument());
    expect(screen.queryByText(/walked/)).toBeNull();
  });
});
