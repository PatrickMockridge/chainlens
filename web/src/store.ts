/**
 * The document store: what is loaded, what is selected, and how documents merge.
 *
 * **Merging is a union by key, and that is the whole of it.** Node and edge keys are
 * content-addressed — `address:bitcoin:bc1q…`, `tx1:out:0` — so the same entity from two
 * documents is the same string, and unioning two documents cannot duplicate anything. That is
 * what makes live expansion cheap: the server returns another document rather than a delta, and
 * the client needs a map rather than a merge algorithm.
 *
 * Nothing here fetches. Loading is the caller's business, so the same store serves the live path
 * (fetched from a local server), the static path (a file somebody dropped in) and the tests.
 */
import type {
  DerivationDocument,
  EvidenceItem,
  LedgerDocument,
  LedgerEdge,
  LedgerNode,
  OverlayDocument,
} from "./schema/documents";
import { asTree } from "./schema/documents";
import { branchesTouching, refsOf, subtreeIds, walkTree } from "./derive/tree";

export interface Store {
  /** Documents loaded so far, in the order they arrived. */
  readonly sources: readonly string[];
  readonly nodes: ReadonlyMap<string, LedgerNode>;
  readonly edges: ReadonlyMap<string, LedgerEdge>;
  readonly overlays: readonly OverlayEntry[];
  readonly derivations: readonly DerivationDocument[];
  /**
   * Address keys the walk admitted but did not expand — where it stopped, rather than where the
   * chain does. Held because it is a *live view's* invitation: the document records the frontier
   * precisely so something can offer to go on, and a UI that dropped it would show a boundary as
   * if it were an ending.
   */
  readonly frontier: ReadonlySet<string>;
  readonly selection: Selection | null;
  /**
   * The derivation branch a reader clicked, when one is open.
   *
   * Orthogonal to `selection` rather than a fourth `Selection` member: a graph key and a tree
   * branch are selected *together* — that is the whole point of the two views being a pair — so
   * folding them into one field would mean a click on one cleared the other.
   */
  readonly branch: string | null;
  readonly warnings: readonly string[];
}

/** Where an overlay came from, so a refresh from the same place replaces rather than stacks. */
export interface OverlayEntry {
  readonly source: string;
  readonly document: OverlayDocument;
}

export type Selection =
  | { kind: "node"; key: string }
  | { kind: "edge"; key: string }
  | { kind: "claim"; id: string };

export const emptyStore: Store = {
  sources: [],
  nodes: new Map(),
  edges: new Map(),
  overlays: [],
  derivations: [],
  frontier: new Set(),
  selection: null,
  branch: null,
  warnings: [],
};

/**
 * Merge a ledger document in, unioning by key.
 *
 * The **key set** does not depend on load order, and that is the property expansion relies on: a
 * node and an edge are identified by content, so unioning two documents cannot duplicate anything
 * and cannot produce a different graph for the same set of documents.
 *
 * **Which description of a shared node you see does depend on load order**: the first one wins.
 * That is deliberate rather than overlooked. Two walks of the same transaction agree on what the
 * chain recorded — `n_inputs`, `n_outputs`, the txid — because those are facts about the
 * transaction. They disagree on `depth` and `is_seed`, which are facts about the *walk*, and the
 * earlier walk is the one whose geometry the reader is looking at. Replacing would silently
 * re-root the graph under them when a second file arrived.
 */
export function addLedger(store: Store, source: string, document: LedgerDocument): Store {
  const nodes = new Map(store.nodes);
  const edges = new Map(store.edges);

  for (const node of document.nodes) {
    if (!nodes.has(node.key)) nodes.set(node.key, node);
  }
  for (const edge of document.edges) {
    if (!edges.has(edge.key)) edges.set(edge.key, edge);
  }

  // The frontier unions rather than replacing, because it is a statement per *walk*: a frontier
  // address that a later walk did expand is the one case where the union is wrong, and it is
  // handled where the button is offered — see `expandable` — rather than by trying to unset it
  // here, which would need to know which document superseded which.
  const frontier = new Set(store.frontier);
  for (const key of document.frontier ?? []) frontier.add(key);

  const warnings = [...store.warnings];
  if (document.truncated) {
    // The walk says why it stopped rather than leaving a small graph looking complete.
    const reasons = Object.keys(document.stop_reasons ?? {});
    warnings.push(
      `${source}: the walk stopped early (${reasons.join(", ") || "reason unrecorded"}), so this ` +
        "graph is a slice rather than the whole neighbourhood",
    );
  }

  return {
    ...store,
    sources: [...store.sources, source],
    nodes,
    edges,
    frontier,
    warnings,
  };
}

/** What `addLedger` actually changed, for a message a person reads. */
export function mergeCounts(
  before: Store,
  after: Store,
): { nodes: number; edges: number; overlays: number; derivations: number } {
  return {
    nodes: after.nodes.size - before.nodes.size,
    edges: after.edges.size - before.edges.size,
    overlays: after.overlays.length - before.overlays.length,
    derivations: after.derivations.length - before.derivations.length,
  };
}

/**
 * Add an overlay, or replace the one the same source gave before.
 *
 * **Keyed by source rather than by content**, unlike nodes and edges, and the difference is
 * deliberate. A node is a fact about the chain, so the same one from two documents *is* the same
 * one. An overlay is a *view of what is known right now*: the server re-joins it on every read,
 * and an annotation recorded a moment ago changes it. Unioning those would stack a stale join
 * beside a fresh one and show an address twice while the two disagreed about what it is.
 *
 * It also removes a fragile check — deduplicating by comparing serialised `claim_refs` — which
 * would have dropped a refreshed overlay precisely when it carried something new.
 */
export function addOverlay(store: Store, source: string, overlay: OverlayDocument): Store {
  const existing = store.overlays.findIndex((entry) => entry.source === source);
  if (existing === -1) return { ...store, overlays: [...store.overlays, { source, document: overlay }] };
  const overlays = [...store.overlays];
  overlays[existing] = { source, document: overlay };
  return { ...store, overlays };
}

export function addDerivation(store: Store, derivation: DerivationDocument): Store {
  if (store.derivations.some((item) => item.claim_id === derivation.claim_id)) return store;
  return { ...store, derivations: [...store.derivations, derivation] };
}

/** The node or edge key a selection names, or ``null`` when it names a claim. */
export function selectedKey(store: Store): string | null {
  const selection = store.selection;
  if (selection === null || selection.kind === "claim") return null;
  return selection.key;
}

export function select(store: Store, selection: Selection | null): Store {
  return { ...store, selection };
}

/** Open, or close, a derivation branch. */
export function selectBranch(store: Store, branch: string | null): Store {
  return { ...store, branch };
}

/**
 * The ledger keys to highlight, from whichever view a reader last worked in.
 *
 * A branch selection wins over the graph selection because it is the more specific statement: a
 * reader who clicked a step of the argument wants that step's evidence shown, not the whole
 * claim's. Both are computed from `graph_refs`, so the two directions cannot disagree about which
 * keys a branch rests on.
 */
export function highlightedKeys(store: Store): Set<string> {
  const keys = new Set<string>();
  const branchId = store.branch;
  if (branchId !== null) {
    for (const derivation of store.derivations) {
      const found = walkTree(asTree(derivation.root)).find((node) => node.id === branchId);
      if (found !== undefined) {
        for (const ref of refsOf(found)) keys.add(ref.key);
        return keys;
      }
    }
  }
  const selection = store.selection;
  if (selection === null) return keys;
  if (selection.kind === "claim") {
    for (const key of refsForClaim(store, selection.id)) keys.add(key);
    return keys;
  }
  keys.add(selection.key);
  return keys;
}

/**
 * The derivation branches to highlight, from the other direction.
 *
 * Every branch in every loaded derivation that rests on the selected key — including branches
 * whose *descendants* rest on it, because a branch's argument is everything beneath it. An
 * unresolved reference still highlights: a branch pointing at a node this graph does not hold is
 * exactly the branch a reader needs to see, since it is the one that says the walk is too shallow.
 */
export function highlightedBranches(store: Store): Set<string> {
  const ids = new Set<string>();
  const selection = store.selection;
  if (selection === null || selection.kind === "claim") return ids;

  for (const derivation of store.derivations) {
    for (const branch of branchesTouching(asTree(derivation.root), selection.key)) {
      for (const id of subtreeIds(branch)) ids.add(id);
    }
  }
  return ids;
}

/** Every node key an overlay associates with a claim, for highlighting. */
export function refsForClaim(store: Store, claimId: string): Set<string> {
  const keys = new Set<string>();
  for (const { document } of store.overlays) {
    for (const ref of document.claim_refs?.[claimId] ?? []) keys.add(ref.key);
  }
  return keys;
}

/** The evidence items the loaded overlays place on one node or edge. */
export function evidenceFor(store: Store, key: string): EvidenceItem[] {
  return store.overlays.flatMap(({ document }) => [
    ...(document.by_node?.[key] ?? []),
    ...(document.by_edge?.[key] ?? []),
  ]);
}

/** Every unresolved reference across the loaded overlays, deduplicated by key. */
export function unresolved(store: Store): { key: string; note?: string }[] {
  const seen = new Map<string, { key: string; note?: string }>();
  for (const { document: overlay } of store.overlays) {
    for (const ref of overlay.unjoined) {
      // A note of `null` means "no reason recorded", which is not a reason — normalised here so
      // a renderer never has to decide what a null note reads as.
      seen.set(ref.key, { key: ref.key, ...(ref.note ? { note: ref.note } : {}) });
    }
  }
  return [...seen.values()];
}

/** Whether a reference resolves in what is loaded, so a panel can offer to fetch or not. */
export function resolves(store: Store, key: string): boolean {
  return store.nodes.has(key) || store.edges.has(key);
}
