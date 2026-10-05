/**
 * One renderer for a derivation, used by both views.
 *
 * There is exactly one of these on purpose. The Explore panel shows the tree under the evidence
 * and the Verify view shows it beside the graph, and the two must not be able to disagree about
 * what a step is called, what the band means, or which words say an assumption is an assumption.
 * A second renderer is a second place for those to drift.
 *
 * Four things it does that a naive tree does not:
 *
 * * **A step is a button, and it is the unit of selection.** Clicking a step opens it as the
 *   current branch, which is what highlights its `graph_refs` in the graph — the tree's half of the
 *   pair of views. Clicking it again closes it, because a selection with no way back is a trap.
 * * **`graph_refs` are shown, counted, and marked when the loaded graph does not hold them.** The
 *   plan's rule is that a dangling reference is never dropped: a branch resting on a transaction
 *   this walk did not reach is *the* branch that tells a reader the walk was too shallow, and
 *   hiding it would make the argument look better supported than it is.
 * * **`detail` renders as data**, never as prose, for the reason the panel gives: an unfamiliar key
 *   turned into a sentence is how a nested object starts reading like a finding.
 * * **The limitations text is rendered verbatim** and sits above the tree rather than behind a
 *   disclosure, because a ratio shown without its caveats is the artifact this library exists to
 *   prevent.
 */
import type { DerivationDocument, DerivationNode } from "../schema/documents";
import { asTree } from "../schema/documents";

/** Past this many levels the rest is not drawn. Named rather than silent — see `deeper` below. */
const MAX_DEPTH = 12;

export interface DerivationTreeProps {
  document: DerivationDocument;
  /** The branch the reader opened, if any. */
  selectedBranch: string | null;
  /** Branches to emphasise, from a selection made in the graph. */
  highlighted: ReadonlySet<string>;
  onSelectBranch: (branchId: string | null) => void;
  onSelectRef: (key: string) => void;
  /** Whether a key is in the loaded graph, so a ref that is not can say so. */
  resolves: (key: string) => boolean;
}

function formatValue(node: DerivationNode): string | null {
  if (node.value === null || node.value === undefined) return null;
  const unit = node.unit ? ` ${node.unit}` : "";
  return `${String(node.value)}${unit}`;
}

function Step({
  node,
  depth,
  props,
}: {
  node: DerivationNode;
  depth: number;
  props: DerivationTreeProps;
}) {
  const { selectedBranch, highlighted, onSelectBranch, onSelectRef, resolves } = props;
  const selected = selectedBranch === node.id;
  const emphasised = highlighted.has(node.id);
  const refs = node.graph_refs ?? [];
  // `exists === false` is the library saying it looked and did not find it. `null` means nobody
  // looked, which is a different thing — the graph here *is* the thing it was joined against, so
  // a key absent from it is absent from this view either way.
  const absent = refs.filter((ref) => ref.exists === false || !resolves(ref.key));
  const value = formatValue(node);
  const children = node.children ?? [];

  const className = [
    "tree-node",
    `tree-${node.kind}`,
    selected ? "selected" : "",
    emphasised ? "highlighted" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <li className={className} data-branch={node.id}>
      <button
        type="button"
        className="tree-label"
        aria-pressed={selected}
        onClick={() => onSelectBranch(selected ? null : node.id)}
      >
        <span className="tree-kind">{node.kind}</span>
        <span className="tree-text">{node.label}</span>
        {value !== null && <span className="tree-value">{value}</span>}
        {node.band && <span className="band">{node.band}</span>}
      </button>

      {node.summary && <p className="tree-summary">{node.summary}</p>}

      {node.detail && node.detail.length > 0 && (
        <dl className="detail tree-detail">
          {node.detail.map((entry) => (
            <div key={entry.key} className="detail-row">
              <dt>{entry.key}</dt>
              <dd data-kind={entry.kind}>
                {entry.value === null || entry.value === undefined
                  ? "—"
                  : Array.isArray(entry.value)
                    ? entry.value.join(", ")
                    : String(entry.value)}
              </dd>
            </div>
          ))}
        </dl>
      )}

      {refs.length > 0 && (
        <p className="tree-refs">
          <span className="tree-refs-label">
            rests on {refs.length} {refs.length === 1 ? "item" : "items"}
          </span>
          {refs.map((ref) => (
            <button
              key={ref.key}
              type="button"
              className={`ref-chip${absent.includes(ref) ? " ref-absent" : ""}`}
              title={ref.note ?? (absent.includes(ref) ? "not in the loaded graph" : "in the loaded graph, click to select")}
              onClick={() => onSelectRef(ref.key)}
            >
              {ref.key}
            </button>
          ))}
        </p>
      )}

      {absent.length > 0 && (
        <p className="tree-absent">
          {absent.length} of {refs.length} not in the loaded view — expand the walk to fetch
          {absent.length === 1 ? " it" : " them"}.
        </p>
      )}

      {children.length > 0 &&
        (depth + 1 < MAX_DEPTH ? (
          <ul>
            {children.map((child) => (
              <Step key={child.id} node={child} depth={depth + 1} props={props} />
            ))}
          </ul>
        ) : (
          // Not drawn, and it says so. A tree that quietly stops reads as a tree that ended.
          <p className="tree-absent">
            {children.length} further step(s) not drawn: this renderer stops at {MAX_DEPTH} levels.
          </p>
        ))}
    </li>
  );
}

export function DerivationTree(props: DerivationTreeProps) {
  const { document } = props;
  return (
    <section className="derivation">
      {/*
        The limitations text is carried on the document and rendered verbatim, never summarised.
        It is swapped by the document itself when a posterior is present, because the standard text
        says the library reports no posterior and a rendered posterior beside it would make the
        artifact contradict itself.
      */}
      <p className="limitations">{document.limitations}</p>
      <ul className="tree">
        <Step node={asTree(document.root)} depth={0} props={props} />
      </ul>
    </section>
  );
}
