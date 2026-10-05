/**
 * The app: one graph, loaded either live or from a file, with the evidence on it.
 *
 * **Live when a server answers, static otherwise, and the difference is always on screen.** The
 * probe is `GET /api/health`; if it answers, the graph is fetched and the header says `live`. If
 * it does not, the app says so and offers to load a document — and a loaded document carries its
 * own `generated_at` and `truncated`, so a reader can always tell a snapshot from a fresh read.
 * That is the same discipline as the library's caching: a replay must not be mistakable for a
 * live observation.
 *
 * Dropping a file is how a *committed export* gets in. `chainlens ui export` writes one, it
 * carries everything the graph needs, and it can be handed to somebody else — which is the point
 * of it being a file rather than a server.
 */
import "@xyflow/react/dist/style.css";

import { useCallback, useEffect, useMemo, useState } from "react";

import { GraphView } from "./graph/GraphView";
import type { LedgerDocument } from "./schema/documents";
import { classify } from "./schema/documents";
import { EvidencePanel } from "./panel/EvidencePanel";
import { VerifyView } from "./views/VerifyView";
import {
  addDerivation,
  addLedger,
  addOverlay,
  emptyStore,
  evidenceFor,
  highlightedKeys,
  mergeCounts,
  select,
  selectBranch,
  selectedKey,
  unresolved,
  type Store,
} from "./store";

type Mode = { kind: "probing" } | { kind: "live"; provider: string } | { kind: "static" };

/**
 * Which view a reader is in.
 *
 * Two views over one store rather than two apps: the graph is the same graph, the selection is the
 * same selection, and switching views must not throw away either. A reader who found a
 * transaction in Explore and then wants to know what rests on it switches rather than reloads.
 */
type View = "explore" | "verify";

export function App() {
  const [store, setStore] = useState<Store>(emptyStore);
  const [mode, setMode] = useState<Mode>({ kind: "probing" });
  const [notice, setNotice] = useState<string | null>(null);
  const [view, setView] = useState<View>("explore");

  const apply = useCallback((source: string, value: unknown) => {
    const classified = classify(value);
    if (classified === null) {
      setNotice(
        `${source} is not a document this app reads. Expected a ` +
          "`chainlens ui export` graph, an evidence overlay, or a derivation.",
      );
      return;
    }
    setStore((current) => {
      const before = current;
      const after =
        classified.kind === "ledger"
          ? addLedger(current, source, classified.document)
          : classified.kind === "overlay"
            ? addOverlay(current, classified.document)
            : addDerivation(current, classified.document);
      const counts = mergeCounts(before, after);
      if (classified.kind === "ledger") {
        setNotice(
          `Loaded ${source}: +${counts.nodes} nodes, +${counts.edges} edges ` +
            `(${after.nodes.size} nodes in total)`,
        );
      }
      return after;
    });
  }, []);

  // Probe once on boot. A server that is not running is the normal case for a static export, so a
  // failed probe is a mode rather than an error.
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    void (async () => {
      try {
        const health = await fetch("/api/health", { signal: controller.signal });
        if (!health.ok) throw new Error(String(health.status));
        const payload = (await health.json()) as { provider?: string };
        const document = (await (await fetch("/api/document", { signal: controller.signal })).json()) as LedgerDocument;
        if (cancelled) return;
        setMode({ kind: "live", provider: payload.provider ?? "unknown" });
        apply("live", document);
      } catch {
        if (!cancelled) setMode({ kind: "static" });
      }
    })();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [apply]);

  const onDrop = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      for (const file of Array.from(event.dataTransfer.files)) {
        void file.text().then((text) => {
          try {
            apply(file.name, JSON.parse(text));
          } catch {
            setNotice(`${file.name} is not JSON`);
          }
        });
      }
    },
    [apply],
  );

  const nodes = useMemo(() => [...store.nodes.values()], [store.nodes]);
  const edges = useMemo(() => [...store.edges.values()], [store.edges]);

  const withEvidence = useMemo(() => {
    const keys = new Set<string>();
    for (const overlay of store.overlays) {
      for (const key of Object.keys(overlay.by_node ?? {})) keys.add(key);
      for (const key of Object.keys(overlay.by_edge ?? {})) keys.add(key);
    }
    return keys;
  }, [store.overlays]);

  // Both highlight sets come from the store rather than being computed here, so that the two views
  // cannot hold different opinions about what a selection points at.
  const highlighted = useMemo(() => highlightedKeys(store), [store]);

  const missing = unresolved(store);

  const onSelect = useCallback(
    (selection: { kind: "node" | "edge"; key: string } | null) =>
      setStore((current) => select(current, selection)),
    [],
  );

  const onSelectRef = useCallback(
    (key: string) =>
      setStore((current) =>
        select(current, current.edges.has(key) ? { kind: "edge", key } : { kind: "node", key }),
      ),
    [],
  );

  const onSelectBranch = useCallback(
    (branchId: string | null) => setStore((current) => selectBranch(current, branchId)),
    [],
  );

  const onSelectClaim = useCallback(
    (claimId: string) => setStore((current) => select(current, { kind: "claim", id: claimId })),
    [],
  );

  return (
    <div className="app" onDrop={onDrop} onDragOver={(event) => event.preventDefault()}>
      <header className="header">
        <div>
          <h1>chainlens</h1>
          <p className="tagline">
            A transaction is a node and an address is a node. Every edge is one recorded input or
            output.
          </p>
        </div>
        <div className="mode" data-mode={mode.kind}>
          {mode.kind === "probing" && "looking for a local server…"}
          {mode.kind === "live" && `live · ${mode.provider}`}
          {mode.kind === "static" && "static · no server answering"}
        </div>
      </header>

      <nav className="views" aria-label="view">
        <button type="button" aria-pressed={view === "explore"} onClick={() => setView("explore")}>
          Explore
        </button>
        <button type="button" aria-pressed={view === "verify"} onClick={() => setView("verify")}>
          Verify
          {store.derivations.length > 0 && ` (${store.derivations.length})`}
        </button>
        <span className="views-note">
          {view === "explore"
            ? "Seed a walk and follow recorded inputs and outputs."
            : "Read the argument behind a finding, joined to the ledger it rests on."}
        </span>
      </nav>

      {/*
        Stated once, in the view rather than in a tooltip, because the misreading it prevents is
        the one a tidy picture invites: that the chain linked these inputs to these outputs.
      */}
      <p className="caveat" role="note">
        <strong>Values are recorded; the linkage is not.</strong> Each edge carries what the ledger
        said for that input or output. No ledger records which input funded which output, so nothing
        here — and nothing anywhere — should be read as saying that one paid the other.
      </p>

      {view === "verify" ? (
        <VerifyView
          store={store}
          nodes={nodes}
          edges={edges}
          withEvidence={withEvidence}
          onSelect={onSelect}
          onSelectBranch={onSelectBranch}
          onSelectClaim={onSelectClaim}
        />
      ) : (
        <main className="layout">
          <section className="canvas">
            {nodes.length === 0 ? (
              <div className="empty">
                <h2>{mode.kind === "probing" ? "Waiting for the server" : "No graph loaded"}</h2>
                <p>
                  Drop a <code>graph.json</code> from <code>chainlens ui export</code> here, or
                  along with an overlay or a derivation. Several documents union by key, so loading
                  a second neighbourhood adds to the first.
                </p>
              </div>
            ) : (
              <GraphView
                nodes={nodes}
                edges={edges}
                highlighted={highlighted}
                withEvidence={withEvidence}
                onSelect={onSelect}
              />
            )}
          </section>

          <aside className="panel">
            <EvidencePanel
              store={store}
              evidence={selectedKey(store) !== null ? evidenceFor(store, selectedKey(store)!) : []}
              missing={missing}
              onSelectClaim={onSelectClaim}
              onSelectBranch={onSelectBranch}
              onSelectRef={onSelectRef}
            />
          </aside>
        </main>
      )}

      {(notice || store.warnings.length > 0) && (
        <footer className="notices">
          {notice && <p>{notice}</p>}
          {store.warnings.map((warning) => (
            <p key={warning} className="warning">
              {warning}
            </p>
          ))}
        </footer>
      )}
    </div>
  );
}
