/**
 * The three things a ledger graph is made of, and how each one admits what it does not say.
 *
 * A node here is not a decoration over data — it is where the graph states its own limits, so the
 * marks matter as much as the labels:
 *
 * * a **transaction** shows its recorded input and output counts, so a node whose edges were
 *   suppressed says `2 out recorded, 0 drawn` rather than looking like a mint;
 * * a **coinbase** is marked, because a transaction with no inputs is a fact worth noticing;
 * * a **CoinJoin** is marked, because reading value *through* it is the most wrong thing this
 *   view could invite;
 * * an **unparsed** node exists so an output with no address is counted rather than dropped.
 */
import { Handle, Position, type NodeProps } from "@xyflow/react";

import type {
  LedgerAddressNode,
  LedgerEdge,
  LedgerNode,
  LedgerTransactionNode,
  LedgerUnparsedNode,
} from "../schema/documents";

export interface NodeData extends Record<string, unknown> {
  node: LedgerNode;
  /** How many of this node's edges the document holds, when it is a transaction. */
  drawnInputs: number;
  drawnOutputs: number;
  hasEvidence: boolean;
  highlighted: boolean;
}

function shorten(text: string, head = 10, tail = 8): string {
  return text.length <= head + tail + 1 ? text : `${text.slice(0, head)}…${text.slice(-tail)}`;
}

function marks(node: LedgerTransactionNode): string[] {
  const found: string[] = [];
  if (node.is_coinbase) found.push("minted");
  if (node.is_coinjoin) found.push("coinjoin");
  if (node.is_partial) found.push("partial");
  if (node.value_complete === false) found.push("values incomplete");
  return found;
}

function Handles() {
  return (
    <>
      <Handle type="target" position={Position.Left} className="handle" />
      <Handle type="source" position={Position.Right} className="handle" />
    </>
  );
}

export function AddressNode({ data }: NodeProps) {
  const { node: rendered, hasEvidence, highlighted } = data as NodeData;
  const node: LedgerAddressNode = rendered as LedgerAddressNode;
  const address = node.address;
  return (
    <div className={`node node-address${highlighted ? " highlighted" : ""}`}>
      <Handles />
      <div className="node-title">{node.is_seed ? "seed address" : "address"}</div>
      <div className="node-label" title={address}>
        {shorten(address)}
      </div>
      <div className="node-meta">
        <span>{node.tx_count ?? 0} txs seen</span>
        {hasEvidence && <span className="badge badge-evidence">evidence</span>}
      </div>
    </div>
  );
}

export function TransactionNode({ data }: NodeProps) {
  const { node: rendered, drawnInputs, drawnOutputs, hasEvidence, highlighted } = data as NodeData;
  const tx: LedgerTransactionNode = rendered as LedgerTransactionNode;
  const recorded = `${tx.n_inputs} in / ${tx.n_outputs} out`;
  const drawn = `${drawnInputs} + ${drawnOutputs} drawn`;
  // A transaction whose recorded counts exceed what is drawn is *saying so*. Without this the
  // node would be a pill that looks complete, which is the failure `is_partial` exists for.
  const suppressed = drawnInputs + drawnOutputs < tx.n_inputs + tx.n_outputs;

  return (
    <div className={`node node-transaction${highlighted ? " highlighted" : ""}`}>
      <Handles />
      <div className="node-title" title={tx.txid}>
        {shorten(tx.txid, 8, 6)}
      </div>
      <div className="node-label">{recorded}</div>
      {suppressed && (
        <div className="node-meta node-meta-warn" title="some of this transaction's edges were not drawn">
          {drawn}
        </div>
      )}
      <div className="node-marks">
        {marks(tx).map((mark) => (
          <span key={mark} className={`badge badge-${mark.replace(" ", "-")}`}>
            {mark}
          </span>
        ))}
        {hasEvidence && <span className="badge badge-evidence">evidence</span>}
      </div>
    </div>
  );
}

export function UnparsedNode({ data }: NodeProps) {
  const { node: rendered, highlighted } = data as NodeData;
  const node: LedgerUnparsedNode = rendered as LedgerUnparsedNode;
  return (
    <div className={`node node-unparsed${highlighted ? " highlighted" : ""}`}>
      <Handles />
      <div className="node-title">no address</div>
      <div className="node-label">{node.edge_count ?? 0} endpoint(s)</div>
    </div>
  );
}

export const nodeTypes = {
  address: AddressNode,
  transaction: TransactionNode,
  unparsed: UnparsedNode,
} as const;

/** The colour a stroke takes, by edge role — the one thing a line must say at a glance. */
export const EDGE_CLASS: Record<string, string> = {
  input: "edge-input",
  output: "edge-output",
  token: "edge-token",
  internal: "edge-internal",
};

export function edgeClass(edge: LedgerEdge): string {
  const base = EDGE_CLASS[edge.role] ?? "edge-output";
  // Change is dashed rather than hidden: it is how value comes back, and a view that dropped it
  // would be hiding the mechanism rather than simplifying the picture.
  return `${base}${edge.is_change ? " edge-change" : ""}${edge.amount_status === "missing" ? " edge-unknown" : ""}`;
}
