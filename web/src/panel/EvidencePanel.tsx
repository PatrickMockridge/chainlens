/**
 * What is known about whatever is selected, and what is known but not here.
 *
 * Three things the panel refuses to do, each because doing it would make the graph look more
 * complete than it is:
 *
 * * **It renders `detail` as data.** The tagged list exists so a renderer never has to guess a
 *   value's type — and never has to render an unfamiliar key as prose, which is how a nested
 *   object becomes a sentence that reads like a finding.
 * * **It keeps a declared assertion visibly declared.** An annotation is styled apart and says
 *   "user-declared" in words, so the distinction survives a screenshot of this panel.
 * * **It lists the evidence that did not resolve.** A claim about an address outside the walk is
 *   not nothing: it is something this view cannot show, and saying so tells a reader to widen the
 *   walk rather than to conclude there is nothing there.
 */
import type { DerivationDocument, EvidenceItem, LedgerEdge, LedgerNode } from "../schema/documents";
import { asTree } from "../schema/documents";
import type { Store } from "../store";
import { selectedKey } from "../store";

export interface EvidencePanelProps {
  store: Store;
  evidence: EvidenceItem[];
  missing: { key: string; note?: string }[];
  onSelectClaim: (claimId: string) => void;
}

function DetailRows({ item }: { item: EvidenceItem }) {
  if (!item.detail || item.detail.length === 0) return null;
  return (
    <dl className="detail">
      {item.detail.map((entry) => (
        <div key={entry.key} className="detail-row">
          <dt>{entry.key}</dt>
          {/* A tagged value renders as data: an int is a decimal string on the wire, so it is
              shown as text rather than coerced back into a number that could round. */}
          <dd data-kind={entry.kind}>{formatValue(entry.value)}</dd>
        </div>
      ))}
    </dl>
  );
}

function formatValue(value: string | number | boolean | string[] | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (Array.isArray(value)) return value.length === 0 ? "—" : value.join(", ");
  return String(value);
}

function describe(key: string): string {
  const parts = key.split(":");
  if (parts[0] === "address") return `address ${parts.slice(2).join(":")}`;
  if (parts[0] === "transaction") return `transaction ${parts.slice(2).join(":")}`;
  if (parts[0] === "unparsed") return `unrecorded endpoints of ${parts.slice(2).join(":")}`;
  return key;
}

function DerivationTree({ document }: { document: DerivationDocument }) {
  const root = asTree(document.root);
  const render = (node: ReturnType<typeof asTree>, depth: number): React.ReactNode => (
    <li key={node.id} className={`tree-node tree-${node.kind}`}>
      <div className="tree-label">
        <span className="tree-kind">{node.kind}</span>
        <span>{node.label}</span>
        {node.band && <span className="band">{node.band}</span>}
      </div>
      {node.summary && <p className="tree-summary">{node.summary}</p>}
      {node.children && node.children.length > 0 && depth < 12 && (
        <ul>{node.children.map((child) => render(child, depth + 1))}</ul>
      )}
    </li>
  );
  return (
    <section className="derivation">
      <h3>Derivation</h3>
      {/*
        The limitations text is carried on the document and rendered verbatim. It is *swapped*
        when a posterior is present, because the standard text says the library reports none.
      */}
      <p className="limitations">{document.limitations}</p>
      <ul className="tree">{render(root, 0)}</ul>
    </section>
  );
}

export function EvidencePanel({ store, evidence, missing, onSelectClaim }: EvidencePanelProps) {
  const selection = store.selection;
  const selectionKey = selectedKey(store);
  const claim =
    selection?.kind === "claim"
      ? (store.derivations.find((item) => item.claim_id === selection.id) ?? null)
      : null;

  return (
    <div className="panel-inner">
      <h2>{selectionKey !== null ? describe(selectionKey) : "Nothing selected"}</h2>
      {!selection && (
        <p className="hint">
          Select a node or an edge. A transaction shows its recorded inputs and outputs; an address
          shows everything said about it, including what a person declared and what a cluster
          hypothesised.
        </p>
      )}

      {selectionKey !== null && <NodeOrEdge store={store} selectionKey={selectionKey} />}

      {evidence.length > 0 && (
        <section>
          <h3>Evidence</h3>
          <ul className="evidence">
            {evidence.map((item, index) => (
              <li key={`${item.kind}-${index}`} className={`evidence-item evidence-${item.kind}`}>
                <div className="evidence-head">
                  <span className="evidence-kind">{item.kind}</span>
                  {item.source && <span className="badge">{item.source}</span>}
                  {/* A declared assertion says so in words, not only in styling. */}
                  {item.source === "user" && <span className="badge badge-declared">user-declared</span>}
                  {item.claim_id && (
                    <button type="button" className="link" onClick={() => onSelectClaim(item.claim_id!)}>
                      show claim
                    </button>
                  )}
                </div>
                <p className="evidence-summary">{item.summary}</p>
                <DetailRows item={item} />
                {item.graph_refs && item.graph_refs.some((ref) => ref.exists === false) && (
                  <p className="unresolved-note">
                    Some of what this rests on is not in the loaded graph — widen the walk to fetch it.
                  </p>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {store.derivations.length > 0 && (
        <section>
          <h3>Claims in this view</h3>
          <ul className="claims">
            {store.derivations.map((item) => (
              <li key={item.claim_id}>
                <button type="button" className="link" onClick={() => onSelectClaim(item.claim_id)}>
                  {item.verdict} — {item.claim_quote.slice(0, 60)}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {claim && <DerivationTree document={claim} />}

      {missing.length > 0 && (
        <section>
          <h3>Known, but not in this graph</h3>
          <p className="hint">
            {missing.length} reference(s) point at nodes this document does not hold. They are listed
            rather than dropped: a claim about an address outside the walk is something this view
            cannot show, which is not the same as nothing being there.
          </p>
          <ul className="missing">
            {missing.slice(0, 12).map((item) => (
              <li key={item.key}>
                <code>{item.key}</code>
                {item.note && <span className="note"> — {item.note}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function NodeOrEdge({ store, selectionKey }: { store: Store; selectionKey: string }) {
  const node: LedgerNode | undefined = store.nodes.get(selectionKey);
  const edge: LedgerEdge | undefined = store.edges.get(selectionKey);

  if (node?.kind === "transaction") {
    return (
      <dl className="detail">
        <div className="detail-row">
          <dt>txid</dt>
          <dd>{node.txid}</dd>
        </div>
        <div className="detail-row">
          <dt>recorded</dt>
          <dd>{`${node.n_inputs} in / ${node.n_outputs} out`}</dd>
        </div>
        <div className="detail-row">
          <dt>values</dt>
          <dd>{node.value_complete ? "complete" : "incomplete — a total would not be a total"}</dd>
        </div>
        {node.is_coinbase && (
          <div className="detail-row">
            <dt>minted</dt>
            <dd>no inputs, so nothing to come from but the block reward</dd>
          </div>
        )}
        {node.is_coinjoin && (
          <div className="detail-row">
            <dt>coinjoin</dt>
            <dd>
              several inputs with equal outputs — reading value through this transaction is the most
              misleading thing this view could invite
            </dd>
          </div>
        )}
        {node.is_partial && (
          <div className="detail-row">
            <dt>partial</dt>
            <dd>some recorded edges were not drawn; the counts above are the recorded ones</dd>
          </div>
        )}
        {node.block_height !== null && node.block_height !== undefined && (
          <div className="detail-row">
            <dt>height</dt>
            <dd>{String(node.block_height)}</dd>
          </div>
        )}
      </dl>
    );
  }

  if (node?.kind === "address") {
    return (
      <dl className="detail">
        <div className="detail-row">
          <dt>address</dt>
          <dd>{node.address}</dd>
        </div>
        <div className="detail-row">
          <dt>transactions seen</dt>
          <dd>{String(node.tx_count ?? 0)}</dd>
        </div>
      </dl>
    );
  }

  if (edge) {
    return (
      <dl className="detail">
        <div className="detail-row">
          <dt>role</dt>
          <dd>{edge.role}</dd>
        </div>
        <div className="detail-row">
          <dt>amount</dt>
          {/* The raw base units, exact. Formatting an amount needs the asset's decimals, and a
              renderer that divided by a power of ten it guessed would be inventing one. */}
          <dd>{edge.amount === null ? "not recorded by the provider" : `${edge.amount} base units`}</dd>
        </div>
        <div className="detail-row">
          <dt>asset</dt>
          <dd>{edge.asset?.symbol ?? "unknown"}{edge.asset?.contract ? ` (${edge.asset.contract})` : ""}</dd>
        </div>
        {edge.is_change && (
          <div className="detail-row">
            <dt>change</dt>
            <dd>returns to an address that funded this transaction</dd>
          </div>
        )}
      </dl>
    );
  }

  return <p className="hint">Not in this document.</p>;
}
