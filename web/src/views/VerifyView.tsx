/**
 * Verify: the argument beside the evidence it rests on.
 *
 * The two panes are a **pair**, not two panes. They are joined by one field — a derivation step's
 * `graph_refs` — and both directions of that join are wired here:
 *
 * * clicking a step highlights the ledger keys it rests on, over in the graph;
 * * clicking a ledger node or edge emphasises every step that rests on it, here in the tree.
 *
 * Neither direction is computed here. Both come from `store.highlightedKeys` /
 * `store.highlightedBranches`, which read the same relation through the same helpers — because a
 * highlight that disagrees with the other pane is worse than no highlight: it says "this is why"
 * about something that is not.
 *
 * **The pane is not the place a ratio is computed.** Everything drawn here — the value, the band,
 * the conservative headline computed from the sensitivity envelope — was computed in Python and
 * arrives on the document. Re-deriving any of it in TypeScript would let the browser and the report
 * disagree about the same finding, and the report is the one that gets quoted.
 */
import { useMemo, useState } from "react";

import { DerivationTree } from "../derive/DerivationTree";
import { PriorControl, planPosterior } from "../derive/PriorControl";
import { Narrative } from "../derive/Narrative";
import { GraphView } from "../graph/GraphView";
import type { LedgerEdge, LedgerNode } from "../schema/documents";
import type { Store } from "../store";
import { highlightedBranches, highlightedKeys, narrativeFor } from "../store";

export interface VerifyViewProps {
  store: Store;
  nodes: readonly LedgerNode[];
  edges: readonly LedgerEdge[];
  /** Keys carrying evidence, so a node can say so without a click. */
  withEvidence: ReadonlySet<string>;
  onSelect: (selection: { kind: "node" | "edge"; key: string } | null) => void;
  onSelectBranch: (branchId: string | null) => void;
  onSelectClaim: (claimId: string) => void;
}

export function VerifyView({
  store,
  nodes,
  edges,
  withEvidence,
  onSelect,
  onSelectBranch,
  onSelectClaim,
}: VerifyViewProps) {
  // The derivation pane keeps its own choice so that clicking a node in the graph — the other half
  // of the pair — does not swap the argument being read out from under the reader.
  const [pinned, setPinned] = useState<string | null>(null);

  const selectedClaim = store.selection?.kind === "claim" ? store.selection.id : null;
  const activeClaimId =
    selectedClaim ?? pinned ?? store.derivations[0]?.claim_id ?? null;
  const active = store.derivations.find((item) => item.claim_id === activeClaimId) ?? null;

  // The prior is the reader's, so it lives here and nowhere else: not in the store (which mirrors
  // documents), not on the server, and not on a document. `null` means "there is no prior", which
  // is the state the library ships in.
  const [priorLogOdds, setPriorLogOdds] = useState<number | null>(null);
  const plan = useMemo(
    () => (active === null ? null : planPosterior(active, priorLogOdds)),
    [active, priorLogOdds],
  );

  const highlighted = highlightedKeys(store);
  const branches = highlightedBranches(store);
  const narrative = active === null ? null : narrativeFor(store, active.claim_id);

  if (store.derivations.length === 0) {
    return (
      <main className="verify verify-empty">
        <div className="empty">
          <h2>No derivation loaded</h2>
          <p>
            A derivation is the argument behind one finding — the claim, the two propositions, the
            measured quantities, the ratio and its sensitivity envelope, or the reason no ratio was
            reported. It is built from a <code>VerificationFinding</code> by{" "}
            <code>ledger/derive.py</code> and written as JSON.
          </p>
          <p>
            Drop one here, together with the <code>graph.json</code> it refers to. Without the graph
            the tree still renders — every step that rests on something outside the walk says so
            rather than disappearing.
          </p>
        </div>
      </main>
    );
  }

  return (
    <main className="verify">
      <section className="canvas">
        {nodes.length === 0 ? (
          <div className="empty">
            <h2>No graph loaded</h2>
            <p>
              The derivation below names the transactions and addresses it rests on, but no ledger
              document is loaded, so none of them can be drawn. Every reference reads as "not in the
              loaded view" until a <code>graph.json</code> for the same chain arrives.
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

      <aside className="panel verify-argument">
        <div className="panel-inner">
          {store.derivations.length > 1 && (
            <section>
              <h3>Claims in this view</h3>
              <ul className="claims">
                {store.derivations.map((item) => (
                  <li key={item.claim_id}>
                    <button
                      type="button"
                      className="link"
                      aria-pressed={item.claim_id === activeClaimId}
                      onClick={() => {
                        setPinned(item.claim_id);
                        onSelectClaim(item.claim_id);
                      }}
                    >
                      {item.verdict} — {item.claim_quote.slice(0, 60)}
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {active && (
            <>
              {/* The space is in the markup rather than left to JSX, which drops a
                  newline-indented line break: without it a screen reader reads the verdict and
                  the method as one word. */}
              <h2>
                {active.verdict} <span className="badge">{active.method}</span>
              </h2>
              {/*
                The quote verbatim. A verdict is about this span of text and nothing else, and a
                paraphrase here would let a reader take the finding as being about the whole post.
              */}
              <blockquote className="claim-quote">{active.claim_quote}</blockquote>

              {/*
                Both statements are shown when both are true. They can hold at once — a step open
                *and* a graph selection — and picking one to display would hide a fact that is
                still the case, which is the same failure as an unstated caveat.
              */}
              <div className="pairing" role="status">
                {store.branch === null && branches.size === 0 ? (
                  <p>
                    Click a step to highlight what it rests on in the graph, or a node or edge to see
                    which steps rest on it.
                  </p>
                ) : (
                  <>
                    {store.branch !== null && (
                      <p>
                        Highlighting <strong>{highlighted.size}</strong> item(s) in the graph from
                        the step you opened.
                      </p>
                    )}
                    {branches.size > 0 && (
                      <p>
                        <strong>{branches.size}</strong> step(s) of this argument rest on what you
                        selected in the graph.
                      </p>
                    )}
                  </>
                )}
              </div>

              {plan !== null && (
                <PriorControl plan={plan} logOdds={priorLogOdds} onChange={setPriorLogOdds} />
              )}

              {/*
                The prose sits under the tree it is about, and only where one has been loaded: a
                narrative is a view of the derivation, not part of it, so its absence is the normal
                case rather than a missing piece.
              */}
              {narrative !== null && <Narrative document={narrative} />}

              <DerivationTree
                document={active}
                selectedBranch={store.branch}
                highlighted={branches}
                onSelectBranch={onSelectBranch}
                onSelectRef={(key) =>
                  onSelect(
                    store.edges.has(key)
                      ? { kind: "edge", key }
                      : { kind: "node", key },
                  )
                }
                resolves={(key) => store.nodes.has(key) || store.edges.has(key)}
                extraChildren={plan?.extraChildren}
                readerSteps={plan?.readerSteps}
                limitations={plan?.limitations}
              />
            </>
          )}
        </div>
      </aside>
    </main>
  );
}
