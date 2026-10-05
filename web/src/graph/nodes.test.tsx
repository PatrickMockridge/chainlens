/**
 * The node components: what the graph says about a transaction, at a glance.
 *
 * This is where the view's honesty lives, so it is asserted directly rather than through the
 * canvas. Testing it through React Flow would need a sized container — which jsdom cannot give,
 * because it does no layout — and the failure would be indistinguishable from a rendering bug.
 * These components are plain DOM, so they are tested as such, inside a provider because the
 * handles need one.
 */
import { ReactFlowProvider, type NodeProps } from "@xyflow/react";
import { render, screen } from "@testing-library/react";
import { createElement, type ReactElement } from "react";
import { describe, expect, it } from "vitest";

import type { LedgerAddressNode, LedgerEdge, LedgerTransactionNode, LedgerUnparsedNode } from "../schema/documents";
import { AddressNode, TransactionNode, UnparsedNode, edgeClass, type NodeData } from "./nodes";

function transaction(overrides: Partial<LedgerTransactionNode> = {}): LedgerTransactionNode {
  return {
    kind: "transaction",
    key: "transaction:bitcoin:tx1",
    txid: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    chain: "bitcoin",
    depth: 1,
    is_seed: false,
    block_height: 800_000,
    block_time: null,
    status: "confirmed",
    is_coinbase: false,
    is_coinjoin: false,
    fee: "1000",
    vsize: 200,
    n_inputs: 2,
    n_outputs: 3,
    total_input_value: "5000",
    total_output_value: "4000",
    value_complete: true,
    is_partial: false,
    flags: [],
    annotation_ids: [],
    ...overrides,
  };
}

const ADDRESS: LedgerAddressNode = {
  kind: "address",
  key: "address:bitcoin:1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2",
  chain: "bitcoin",
  address: "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2",
  depth: 0,
  is_seed: true,
  tx_count: 4,
  balance: null,
  flags: [],
  annotation_ids: [],
};

const UNPARSED: LedgerUnparsedNode = {
  kind: "unparsed",
  key: "unparsed:bitcoin:tx1",
  chain: "bitcoin",
  txid: "tx1",
  edge_count: 2,
  total_value: "3000",
};

function data(node: NodeData["node"], overrides: Partial<NodeData> = {}): NodeData {
  return {
    node,
    drawnInputs: 0,
    drawnOutputs: 0,
    hasEvidence: false,
    highlighted: false,
    ...overrides,
  };
}

/**
 * Render one node component with the data it reads.
 *
 * One cast per render, because React Flow's `NodeProps` carries a dozen fields a node component
 * never touches — position, drag state, parentage — and supplying them all would be noise that
 * hides which fields the assertions are actually about.
 */
function draw(Component: (props: NodeProps) => ReactElement, node: NodeData) {
  const props = { id: "n1", data: node, selected: false } as unknown as NodeProps;
  return render(<ReactFlowProvider>{createElement(Component, props)}</ReactFlowProvider>);
}

describe("a transaction node", () => {
  it("shows the counts the ledger recorded", () => {
    draw(TransactionNode, data(transaction()));
    expect(screen.getByText("2 in / 3 out")).toBeInTheDocument();
  });

  it("says when fewer edges were drawn than recorded", () => {
    // The failure this prevents: a transaction whose outputs fell under a value floor would
    // otherwise draw as inputs only, which is what a mint looks like.
    draw(TransactionNode, data(transaction(), { drawnInputs: 2, drawnOutputs: 0 }));
    expect(screen.getByText(/2 \+ 0 drawn/)).toBeInTheDocument();
  });

  it("says nothing about drawing when nothing was suppressed", () => {
    draw(TransactionNode, data(transaction(), { drawnInputs: 2, drawnOutputs: 3 }));
    expect(screen.queryByText(/drawn/)).toBeNull();
  });

  it("marks a minted transaction", () => {
    draw(TransactionNode, data(transaction({ is_coinbase: true })));
    expect(screen.getByText("minted")).toBeInTheDocument();
  });

  it("marks a coinjoin, because reading through one is the worst misreading available", () => {
    draw(TransactionNode, data(transaction({ is_coinjoin: true })));
    expect(screen.getByText("coinjoin")).toBeInTheDocument();
  });

  it("marks a transaction whose values are incomplete", () => {
    draw(TransactionNode, data(transaction({ value_complete: false })));
    expect(screen.getByText("values incomplete")).toBeInTheDocument();
  });

  it("marks a transaction as partial in its own right", () => {
    draw(TransactionNode, data(transaction({ is_partial: true })));
    expect(screen.getByText("partial")).toBeInTheDocument();
  });

  it("marks a node carrying evidence", () => {
    draw(TransactionNode, data(transaction(), { hasEvidence: true }));
    expect(screen.getByText("evidence")).toBeInTheDocument();
  });

  it("highlights a node a selection points at", () => {
    const { container } = draw(TransactionNode, data(transaction(), { highlighted: true }));
    expect(container.querySelector(".node.highlighted")).not.toBeNull();
  });
});

describe("an address node", () => {
  it("says which one is the seed, and how much of its history was seen", () => {
    draw(AddressNode, data(ADDRESS));
    expect(screen.getByText("seed address")).toBeInTheDocument();
    expect(screen.getByText("4 txs seen")).toBeInTheDocument();
  });

  it("shortens a long address but keeps the whole one reachable", () => {
    draw(AddressNode, data(ADDRESS));
    expect(screen.getByTitle(ADDRESS.address)).toBeInTheDocument();
    expect(screen.queryByText(ADDRESS.address)).toBeNull();
  });
});

describe("an unparsed node", () => {
  it("counts what had no address rather than showing nothing", () => {
    draw(UnparsedNode, data(UNPARSED));
    expect(screen.getByText("2 endpoint(s)")).toBeInTheDocument();
  });
});

describe("an edge's class", () => {
  const base: LedgerEdge = {
    key: "tx1:out:0",
    src: "transaction:bitcoin:tx1",
    dst: "address:bitcoin:x",
    chain: "bitcoin",
    txid: "tx1",
    role: "output",
    index: 0,
    asset: null,
    amount: "100",
    amount_status: "recorded",
    via: "utxo",
    is_change: false,
    script_type: null,
    block_height: null,
    block_time: null,
    spent: null,
    spent_by_txid: null,
    annotation_ids: [],
  };

  it("distinguishes the role", () => {
    expect(edgeClass(base)).toContain("edge-output");
    expect(edgeClass({ ...base, role: "token" })).toContain("edge-token");
    expect(edgeClass({ ...base, role: "internal" })).toContain("edge-internal");
  });

  it("dashes change rather than hiding it", () => {
    expect(edgeClass({ ...base, is_change: true })).toContain("edge-change");
  });

  it("dashes an unknown amount differently from a known one", () => {
    expect(edgeClass({ ...base, amount_status: "missing" })).toContain("edge-unknown");
    expect(edgeClass(base)).not.toContain("edge-unknown");
  });
});
