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
import { describe, expect, it } from "vitest";

import type { DerivationDocument, LedgerDocument } from "./schema/documents";
import { App } from "./App";

const here = dirname(fileURLToPath(import.meta.url));
const fixtures = JSON.parse(
  readFileSync(join(here, "..", "..", "tests", "ledger", "fixtures", "graph-document.json"), "utf8"),
) as { ledgers: Record<string, LedgerDocument>; derivations: Record<string, DerivationDocument> };

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
