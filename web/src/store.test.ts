/**
 * The store: how documents merge, and what that mechanism has to guarantee.
 *
 * Merging is a union by key, which is only safe because the keys are content-addressed. These
 * tests hold what that buys — the same node from two documents is one node, and the *set* of keys
 * does not depend on load order — and what it deliberately does not: which description of a shared
 * node is shown is the first one, because `depth` and `is_seed` are facts about a walk rather than
 * about the chain.
 */
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import type { LedgerDocument, OverlayDocument } from "./schema/documents";
import { classify } from "./schema/documents";
import {
  addLedger,
  addOverlay,
  emptyStore,
  evidenceFor,
  mergeCounts,
  refsForClaim,
  resolves,
  select,
  selectedKey,
  unresolved,
} from "./store";

const here = dirname(fileURLToPath(import.meta.url));
const fixtures = JSON.parse(
  readFileSync(join(here, "..", "..", "tests", "ledger", "fixtures", "graph-document.json"), "utf8"),
) as { ledgers: Record<string, LedgerDocument>; overlays: Record<string, OverlayDocument> };

const bitcoin = fixtures.ledgers["bitcoin"]!;
const evm = fixtures.ledgers["evm"]!;
const overlay = fixtures.overlays["bitcoin"]!;

describe("classifying a dropped file", () => {
  it("recognises each of the three documents", () => {
    expect(classify(bitcoin)?.kind).toBe("ledger");
    expect(classify(overlay)?.kind).toBe("overlay");
    expect(classify(fixtures.ledgers["empty"])?.kind).toBe("ledger");
  });

  it("refuses something that is none of them", () => {
    expect(classify({ hello: "world" })).toBeNull();
    expect(classify(null)).toBeNull();
  });
});

describe("merging by key", () => {
  it("loads a document whole", () => {
    const store = addLedger(emptyStore, "a.json", bitcoin);
    expect(store.nodes.size).toBe(bitcoin.nodes.length);
    expect(store.edges.size).toBe(bitcoin.edges.length);
  });

  it("unions two documents rather than replacing one with the other", () => {
    const first = addLedger(emptyStore, "a.json", bitcoin);
    const both = addLedger(first, "b.json", evm);
    expect(both.nodes.size).toBeGreaterThanOrEqual(first.nodes.size);
    expect(both.sources).toEqual(["a.json", "b.json"]);
  });

  it("counts only what a second load actually added", () => {
    const first = addLedger(emptyStore, "a.json", bitcoin);
    const again = addLedger(first, "a-again.json", bitcoin);
    expect(mergeCounts(first, again)).toEqual({ nodes: 0, edges: 0, overlays: 0, derivations: 0 });
  });

  it("cannot duplicate a node, because the key is the identity", () => {
    const first = addLedger(emptyStore, "a.json", bitcoin);
    const again = addLedger(first, "a.json", bitcoin);
    expect(again.nodes.size).toBe(first.nodes.size);
    expect(new Set(again.nodes.keys()).size).toBe(again.nodes.size);
  });

  it("produces the same key set whichever order the documents arrive in", () => {
    // The property expansion relies on. `depth` and `is_seed` differ per walk, so *which*
    // description of a shared node is shown depends on load order — but nothing appears or
    // disappears.
    const forwards = addLedger(addLedger(emptyStore, "a.json", bitcoin), "b.json", evm);
    const backwards = addLedger(addLedger(emptyStore, "b.json", evm), "a.json", bitcoin);
    expect([...forwards.nodes.keys()].sort()).toEqual([...backwards.nodes.keys()].sort());
    expect([...forwards.edges.keys()].sort()).toEqual([...backwards.edges.keys()].sort());
  });

  it("keeps the first description of a node the two walks disagree about", () => {
    // A deliberate order dependence, and the one place it shows: `depth` is a fact about the walk
    // rather than about the transaction, so replacing it would re-root the graph a reader is
    // already looking at.
    const withDepth = (depth: number): LedgerDocument => ({
      ...bitcoin,
      nodes: bitcoin.nodes.map((node) =>
        node.kind === "transaction" ? { ...node, depth } : node,
      ),
    });
    const key = bitcoin.nodes.find((node) => node.kind === "transaction")!.key;
    const first = addLedger(addLedger(emptyStore, "a.json", withDepth(1)), "b.json", withDepth(9));
    expect((first.nodes.get(key) as { depth: number }).depth).toBe(1);
  });

  it("warns when a walk stopped early, rather than leaving a slice looking whole", () => {
    const truncated = fixtures.ledgers["truncated"]!;
    const store = addLedger(emptyStore, "truncated.json", truncated);
    expect(truncated.truncated).toBe(true);
    expect(store.warnings.some((warning) => warning.includes("stopped early"))).toBe(true);
  });

  it("says nothing about a complete walk", () => {
    const store = addLedger(emptyStore, "a.json", bitcoin);
    expect(store.warnings).toEqual([]);
  });
});

describe("the overlay, and what it does not fit", () => {
  it("finds the evidence on a node and on an edge", () => {
    const store = addOverlay(addLedger(emptyStore, "a.json", bitcoin), overlay);
    const nodeKeys = Object.keys(overlay.by_node ?? {});
    const edgeKeys = Object.keys(overlay.by_edge ?? {});
    expect(nodeKeys.length).toBeGreaterThan(0);
    expect(evidenceFor(store, nodeKeys[0]!).length).toBeGreaterThan(0);
    expect(evidenceFor(store, edgeKeys[0]!).length).toBeGreaterThan(0);
  });

  it("answers with nothing, rather than failing, for a key it does not know", () => {
    const store = addOverlay(addLedger(emptyStore, "a.json", bitcoin), overlay);
    expect(evidenceFor(store, "address:bitcoin:nobody")).toEqual([]);
  });

  it("maps a claim to every key it touches", () => {
    const store = addOverlay(addLedger(emptyStore, "a.json", bitcoin), overlay);
    const claimId = Object.keys(overlay.claim_refs ?? {})[0]!;
    const refs = refsForClaim(store, claimId);
    expect(refs.size).toBeGreaterThan(0);
    for (const key of refs) expect(typeof key).toBe("string");
  });

  it("reports evidence that resolved to nothing, instead of dropping it", () => {
    const store = addOverlay(addLedger(emptyStore, "a.json", bitcoin), overlay);
    const missing = unresolved(store);
    expect(missing.length).toBeGreaterThan(0);
    // Nothing that did not resolve is in the graph, and the app says so rather than showing an
    // empty node.
    for (const item of missing) expect(resolves(store, item.key)).toBe(false);
  });

  it("does not load the same overlay twice", () => {
    const first = addOverlay(emptyStore, overlay);
    expect(addOverlay(first, overlay)).toBe(first);
  });
});

describe("selection", () => {
  it("names a key for a node or an edge, and not for a claim", () => {
    const withNode = select(emptyStore, { kind: "node", key: "address:bitcoin:x" });
    expect(selectedKey(withNode)).toBe("address:bitcoin:x");

    const withClaim = select(emptyStore, { kind: "claim", id: "claim:1" });
    expect(selectedKey(withClaim)).toBeNull();
    expect(withClaim.selection).toEqual({ kind: "claim", id: "claim:1" });
  });

  it("can be cleared", () => {
    const cleared = select(select(emptyStore, { kind: "node", key: "x" }), null);
    expect(cleared.selection).toBeNull();
  });
});
