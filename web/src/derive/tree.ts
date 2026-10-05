/**
 * Walking a derivation, and the two directions the two views have to agree about.
 *
 * A derivation branch carries `graph_refs` — the ledger nodes and edges that step rests on. That
 * one field is what makes the two views a *pair* rather than two panes:
 *
 * * selecting a branch highlights the graph keys it rests on;
 * * selecting a graph key highlights every branch that rests on it.
 *
 * Both are the same relation read in opposite directions, so both live here rather than in either
 * component. If one view computed it and the other guessed, the second direction would silently
 * disagree with the first — and a highlight that points at the wrong branch is worse than none,
 * because it says "this is why" about something that is not.
 *
 * Everything here is pure and total: a truncated or unexpected tree yields fewer results, never an
 * exception, because a renderer that throws loses the whole page over one malformed node.
 */
import type { DerivationNode, GraphRef } from "../schema/documents";

/** Every step of a tree, depth first, including the root. */
export function walkTree(root: DerivationNode, limit = 5000): DerivationNode[] {
  const found: DerivationNode[] = [];
  const stack: DerivationNode[] = [root];
  while (stack.length > 0 && found.length < limit) {
    const node = stack.pop()!;
    found.push(node);
    // Reversed so the traversal reads top-down, which is the order a reader sees.
    for (const child of [...(node.children ?? [])].reverse()) stack.push(child);
  }
  return found;
}

/** The branches of a tree that rest on a given ledger key. */
export function branchesTouching(root: DerivationNode, key: string): DerivationNode[] {
  return walkTree(root).filter((node) =>
    (node.graph_refs ?? []).some((ref) => ref.key === key),
  );
}

/**
 * The ledger keys a branch rests on, including its descendants'.
 *
 * Descendants are included because a branch's *argument* is everything beneath it: highlighting
 * only the step a reader clicked would show a fragment of the reasoning and leave the rest of the
 * graph unmarked, which understates what the branch is claiming.
 */
export function refsOf(node: DerivationNode): GraphRef[] {
  const seen = new Map<string, GraphRef>();
  for (const step of walkTree(node)) {
    for (const ref of step.graph_refs ?? []) seen.set(ref.key, ref);
  }
  return [...seen.values()];
}

/** The identifiers of a branch and everything beneath it, for highlighting a subtree. */
export function subtreeIds(node: DerivationNode): Set<string> {
  return new Set(walkTree(node).map((step) => step.id));
}

/** The chain of ancestors of a branch, from the root down to it, for showing the path taken. */
export function pathTo(root: DerivationNode, id: string): DerivationNode[] {
  const search = (node: DerivationNode, trail: DerivationNode[]): DerivationNode[] | null => {
    const here = [...trail, node];
    if (node.id === id) return here;
    for (const child of node.children ?? []) {
      const found = search(child, here);
      if (found !== null) return found;
    }
    return null;
  };
  return search(root, []) ?? [];
}

/** How deep a tree goes, which is what a renderer needs to decide whether to keep nesting. */
export function depthOf(root: DerivationNode): number {
  const measure = (node: DerivationNode): number =>
    node.children && node.children.length > 0
      ? 1 + Math.max(...node.children.map(measure))
      : 1;
  return measure(root);
}
