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

export interface Store {
  /** Documents loaded so far, in the order they arrived. */
  readonly sources: readonly string[];
  readonly nodes: ReadonlyMap<string, LedgerNode>;
  readonly edges: ReadonlyMap<string, LedgerEdge>;
  readonly overlays: readonly OverlayDocument[];
  readonly derivations: readonly DerivationDocument[];
  readonly selection: Selection | null;
  readonly warnings: readonly string[];
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
  selection: null,
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

export function addOverlay(store: Store, overlay: OverlayDocument): Store {
  const known = new Set(store.overlays.map((item) => JSON.stringify(item.claim_refs)));
  if (known.has(JSON.stringify(overlay.claim_refs))) return store;
  return { ...store, overlays: [...store.overlays, overlay] };
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

/** Every node key an overlay associates with a claim, for highlighting. */
export function refsForClaim(store: Store, claimId: string): Set<string> {
  const keys = new Set<string>();
  for (const overlay of store.overlays) {
    for (const ref of overlay.claim_refs?.[claimId] ?? []) keys.add(ref.key);
  }
  return keys;
}

/** The evidence items the loaded overlays place on one node or edge. */
export function evidenceFor(store: Store, key: string): EvidenceItem[] {
  return store.overlays.flatMap((overlay) => [
    ...(overlay.by_node?.[key] ?? []),
    ...(overlay.by_edge?.[key] ?? []),
  ]);
}

/** Every unresolved reference across the loaded overlays, deduplicated by key. */
export function unresolved(store: Store): { key: string; note?: string }[] {
  const seen = new Map<string, { key: string; note?: string }>();
  for (const overlay of store.overlays) {
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
