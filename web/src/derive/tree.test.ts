/**
 * The two directions of the join, at the level they are actually implemented.
 *
 * The views are a pair because of one relation: a step's `graph_refs`. Both directions are read
 * here rather than through a component, because a highlight that points at the wrong branch is
 * worse than none — and a component test that asserted a class name would not notice the relation
 * being read the wrong way round.
 *
 * The tree is written by hand rather than taken from the fixture so these tests fail for one
 * reason. That the real, engine-produced derivations walk the same way is asserted in
 * `views/VerifyView.test.tsx`, which loads them.
 */
import { describe, expect, it } from "vitest";

import type { DerivationNode, GraphRef } from "../schema/documents";
import { branchesTouching, depthOf, pathTo, refsOf, subtreeIds, walkTree } from "./tree";

/** A reference of the kind its key implies, the same way the library spells them. */
function ref(key: string, exists: boolean | null = true): GraphRef {
  const isNode = /^(transaction|address|unparsed|entity):/.test(key);
  return { kind: isNode ? "node" : "edge", key, exists, note: null };
}

/**
 * A tree with the shape that matters: a step that rests on something, a step that rests on nothing,
 * and a parent whose *descendant* rests on something. That last one is the case a naive
 * implementation gets wrong.
 */
const TREE: DerivationNode = {
  id: "root",
  kind: "claim",
  label: "the claim",
  children: [
    {
      id: "verdict",
      kind: "verdict",
      label: "supported",
      children: [
        {
          id: "evidence",
          kind: "evidence",
          label: "what the chain recorded",
          graph_refs: [ref("transaction:bitcoin:tx1"), ref("address:bitcoin:A")],
          children: [
            {
              id: "transfer",
              kind: "evidence",
              label: "the transfer",
              graph_refs: [ref("tx1:out:0"), ref("transaction:bitcoin:tx1")],
            },
          ],
        },
        { id: "because", kind: "because", label: "the reason", graph_refs: [] },
      ],
    },
    { id: "caveat", kind: "caveat", label: "a caveat" },
  ],
};

describe("walking a tree", () => {
  it("visits every step, root first, in the order a reader sees them", () => {
    expect(walkTree(TREE).map((node) => node.id)).toEqual([
      "root",
      "verdict",
      "evidence",
      "transfer",
      "because",
      "caveat",
    ]);
  });

  it("stops at the limit rather than walking an unexpected document forever", () => {
    expect(walkTree(TREE, 2).map((node) => node.id)).toEqual(["root", "verdict"]);
  });

  it("measures depth", () => {
    expect(depthOf(TREE)).toBe(4);
    expect(depthOf({ id: "only", kind: "claim", label: "x" })).toBe(1);
  });
});

describe("the branch → graph direction", () => {
  it("finds the steps resting on a key, exactly", () => {
    expect(branchesTouching(TREE, "tx1:out:0").map((node) => node.id)).toEqual(["transfer"]);
  });

  it("counts a step twice only once when two of its refs name the same key", () => {
    // `tx1:out:0` on the child and `transaction:bitcoin:tx1` on both parent and child: the parent
    // is reached once, not once per key.
    expect(branchesTouching(TREE, "transaction:bitcoin:tx1").map((node) => node.id)).toEqual([
      "evidence",
      "transfer",
    ]);
  });

  it("answers with nothing for a key no step rests on", () => {
    expect(branchesTouching(TREE, "address:bitcoin:nowhere")).toEqual([]);
  });

  it("gathers the keys a step rests on, including its descendants'", () => {
    // The descendant's keys are included because a step's *argument* is everything beneath it.
    // Dropping them would show a fragment of the reasoning and leave the rest of the graph
    // unmarked, understating what the step claims.
    const evidence = walkTree(TREE).find((node) => node.id === "evidence")!;
    expect(refsOf(evidence).map((item) => item.key).sort()).toEqual([
      "address:bitcoin:A",
      "transaction:bitcoin:tx1",
      "tx1:out:0",
    ]);
  });

  it("collapses a key named by two steps into one", () => {
    const evidence = walkTree(TREE).find((node) => node.id === "evidence")!;
    const keys = refsOf(evidence).map((item) => item.key);
    expect(new Set(keys).size).toBe(keys.length);
  });
});

describe("the graph → branch direction", () => {
  it("names a step and everything beneath it, because that is the argument", () => {
    const evidence = walkTree(TREE).find((node) => node.id === "evidence")!;
    expect([...subtreeIds(evidence)].sort()).toEqual(["evidence", "transfer"]);
  });

  it("keeps a reference that did not resolve, since that is the step a reader needs", () => {
    // A step pointing at a transaction this walk did not reach is the one that says the walk was
    // too shallow. Dropping it would make the argument look better supported than it is.
    const dangling: DerivationNode = {
      id: "dangling",
      kind: "evidence",
      label: "outside the walk",
      graph_refs: [ref("tx9:out:0", false)],
    };
    expect(branchesTouching(dangling, "tx9:out:0").map((node) => node.id)).toEqual(["dangling"]);
  });

  it("treats an unlooked-at reference the same as a missing one, because here it is missing", () => {
    // `exists === null` means "nobody has looked". The graph *is* the thing it would be looked up
    // in, so a null still highlights — the step is not less of an argument for being unverified.
    const unlooked: DerivationNode = {
      id: "unlooked",
      kind: "evidence",
      label: "?",
      graph_refs: [ref("tx8:out:0", null)],
    };
    expect(branchesTouching(unlooked, "tx8:out:0").map((node) => node.id)).toEqual(["unlooked"]);
  });
});

describe("pathTo", () => {
  it("gives the chain from the root down to a step", () => {
    expect(pathTo(TREE, "transfer").map((node) => node.id)).toEqual([
      "root",
      "verdict",
      "evidence",
      "transfer",
    ]);
  });

  it("is empty for an id that is not in the tree", () => {
    expect(pathTo(TREE, "nobody")).toEqual([]);
  });
});
