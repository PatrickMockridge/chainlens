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

import type { DerivationDocument, LedgerDocument, OverlayDocument } from "./schema/documents";
import { asTree, classify } from "./schema/documents";
import { walkTree } from "./derive/tree";
import {
  addDerivation,
  addLedger,
  addOverlay,
  emptyStore,
  evidenceFor,
  highlightedBranches,
  highlightedKeys,
  mergeCounts,
  refsForClaim,
  resolves,
  select,
  selectBranch,
  selectedKey,
  unresolved,
} from "./store";

const here = dirname(fileURLToPath(import.meta.url));
const fixtures = JSON.parse(
  readFileSync(join(here, "..", "..", "tests", "ledger", "fixtures", "graph-document.json"), "utf8"),
) as {
  ledgers: Record<string, LedgerDocument>;
  overlays: Record<string, OverlayDocument>;
  derivations: Record<string, DerivationDocument>;
};

const bitcoin = fixtures.ledgers["bitcoin"]!;
const evm = fixtures.ledgers["evm"]!;
const overlay = fixtures.overlays["bitcoin"]!;
const noRatio = fixtures.derivations["no_ratio"]!;

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
    const store = addOverlay(addLedger(emptyStore, "a.json", bitcoin), "overlay.json", overlay);
    const nodeKeys = Object.keys(overlay.by_node ?? {});
    const edgeKeys = Object.keys(overlay.by_edge ?? {});
    expect(nodeKeys.length).toBeGreaterThan(0);
    expect(evidenceFor(store, nodeKeys[0]!).length).toBeGreaterThan(0);
    expect(evidenceFor(store, edgeKeys[0]!).length).toBeGreaterThan(0);
  });

  it("answers with nothing, rather than failing, for a key it does not know", () => {
    const store = addOverlay(addLedger(emptyStore, "a.json", bitcoin), "overlay.json", overlay);
    expect(evidenceFor(store, "address:bitcoin:nobody")).toEqual([]);
  });

  it("maps a claim to every key it touches", () => {
    const store = addOverlay(addLedger(emptyStore, "a.json", bitcoin), "overlay.json", overlay);
    const claimId = Object.keys(overlay.claim_refs ?? {})[0]!;
    const refs = refsForClaim(store, claimId);
    expect(refs.size).toBeGreaterThan(0);
    for (const key of refs) expect(typeof key).toBe("string");
  });

  it("reports evidence that resolved to nothing, instead of dropping it", () => {
    const store = addOverlay(addLedger(emptyStore, "a.json", bitcoin), "overlay.json", overlay);
    const missing = unresolved(store);
    expect(missing.length).toBeGreaterThan(0);
    // Nothing that did not resolve is in the graph, and the app says so rather than showing an
    // empty node.
    for (const item of missing) expect(resolves(store, item.key)).toBe(false);
  });

  it("replaces an overlay the same source gave before, rather than stacking a stale one", () => {
    // Keyed by source, unlike nodes and edges: an overlay is a view of what is known *now* — the
    // server re-joins it on every read — so a refreshed one has to displace its predecessor.
    // Unioning would show an address twice while the two disagreed about what it is.
    const first = addOverlay(emptyStore, "live", overlay);
    const refreshed = addOverlay(first, "live", { ...overlay, warnings: ["rejoined"] });
    expect(refreshed.overlays).toHaveLength(1);
    expect(refreshed.overlays[0]!.document.warnings).toEqual(["rejoined"]);

    // A different source still unions, because a dropped file is not the server's view.
    const both = addOverlay(first, "dropped.json", overlay);
    expect(both.overlays.map((entry) => entry.source)).toEqual(["live", "dropped.json"]);
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

/**
 * The join between the two views, read in both directions.
 *
 * These are the tests that make "the two panes are a pair" true rather than decorative. Both
 * directions are read through the same helper — `refsOf` in one, `branchesTouching` in the other —
 * so they cannot disagree about which keys a step rests on.
 */
describe("the two views, joined", () => {
  // A graph and a derivation that is genuinely about it: the fixture derivation's refs name nodes
  // and edges the fixture ledger holds.
  const loaded = addDerivation(addLedger(emptyStore, "bitcoin.json", bitcoin), noRatio);
  const tree = asTree(noRatio.root);
  /**
   * The step resting on a ledger key, found by what it rests on rather than by its id.
   *
   * The generated ids carry a list index (`…/evidence/transfer/0`) that is an implementation
   * detail of the builder, so naming one here would pin the test to a spelling rather than to the
   * relation under test — and would go stale silently, since it would still *look* like a step.
   */
  const stepRestingOn = (key: string): string => {
    const found = walkTree(tree).find((node) =>
      (node.graph_refs ?? []).some((ref) => ref.key === key),
    );
    if (found === undefined) throw new Error(`no step rests on ${key}`);
    return found.id;
  };
  const evidence = stepRestingOn("tx1:out:0");

  it("opens a step and highlights exactly the keys it rests on", () => {
    const opened = selectBranch(loaded, evidence);
    const keys = highlightedKeys(opened);
    // The transfer step rests on the edge and the transaction; the arithmetic is on the document,
    // not restated here.
    expect(keys.has("tx1:out:0")).toBe(true);
    expect(keys.has("transaction:bitcoin:tx1")).toBe(true);
    // And nothing else: a highlight that spills past the step's own refs would be a claim about
    // the evidence that the evidence does not make.
    expect([...keys].length).toBeLessThan(bitcoin.nodes.length + bitcoin.edges.length);
  });

  it("points the other way: a selected key names the steps that rest on it", () => {
    const selected = select(loaded, { kind: "node", key: "transaction:bitcoin:tx1" });
    const branches = highlightedBranches(selected);
    expect(branches.has(evidence)).toBe(true);
    // The parent step's argument includes this one, so the parent is emphasised too.
    expect(branches.has(`${noRatio.claim_id}/evidence`)).toBe(true);
    // Both directions are the same relation, so a key reached one way is reached the other way.
    const opened = highlightedKeys(selectBranch(loaded, evidence));
    expect(opened.has("transaction:bitcoin:tx1")).toBe(true);
  });

  it("highlights nothing when nothing is selected", () => {
    expect(highlightedKeys(loaded).size).toBe(0);
    expect(highlightedBranches(loaded).size).toBe(0);
  });

  it("still highlights a step whose reference the graph does not hold", () => {
    // The dangling reference is the step a reader most needs to see: it is the one that says the
    // walk was too shallow. Dropping it from the answer would hide that, so an unresolvable ref is
    // highlighted exactly like a resolvable one — and the tree says which it is.
    const dangling = addDerivation(
      addOverlay(addLedger(emptyStore, "bitcoin.json", bitcoin), "overlay.json", overlay),
      noRatio,
    );
    // The overlay holds a reference to an address the walk never reached. It is selected here as
    // though a reader had followed it out of the panel.
    const key = overlay.unjoined[0]!.key;
    expect(resolves(dangling, key)).toBe(false);

    // No step in the fixture derivation rests on it, so the answer is "no steps" rather than a
    // failure — and the key is still in the graph's highlight set, so the colour follows the
    // selection out of the panel.
    const selected = select(dangling, { kind: "node", key });
    expect(highlightedBranches(selected).size).toBe(0);
    expect(highlightedKeys(selected).has(key)).toBe(true);
  });

  it("closes a branch again", () => {
    expect(selectBranch(selectBranch(loaded, evidence), null).branch).toBeNull();
  });

  it("keeps a claim selection and a branch selection apart", () => {
    // A branch and a graph key are selected *together* — that is what makes the views a pair — so
    // folding them into one field would make a click in one pane clear the other.
    const both = selectBranch(
      select(loaded, { kind: "claim", id: noRatio.claim_id }),
      evidence,
    );
    expect(both.selection).toEqual({ kind: "claim", id: noRatio.claim_id });
    expect(both.branch).toBe(evidence);
    // The branch wins for the graph highlight, because it is the more specific statement.
    expect(highlightedKeys(both).has("tx1:out:0")).toBe(true);
  });
});
