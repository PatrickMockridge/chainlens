/**
 * The typed view of the generated schemas: what the app imports.
 *
 * Everything here is derived from `*.gen.ts`, which is generated from the JSON Schema, which is
 * generated from the pydantic models. So a field added in Python reaches the app's editor as a
 * type error rather than as `undefined` at runtime.
 *
 * **One thing is not derivable, and it is documented rather than hidden.** `DerivationNode`
 * contains `children: DerivationNode[]`, so it is recursive — and zod cannot infer the type of a
 * schema that refers to itself, which is why the generator emits it through `z.lazy` with a bare
 * `ZodType` annotation. Its *validation* is complete; only the static type is `unknown`. So the
 * tree's type is written here and the parsed document is cast once, in `asTree`, rather than
 * scattering casts through the renderer.
 *
 * The field set is not taken on trust: the contract test compares this schema's shape against
 * the JSON Schema's `properties`, so a field that exists in Python and not here fails the build.
 */
import { z } from "zod";

import { DerivationDocumentSchema, DerivationNodeSchema } from "./derivation.gen";
import { LedgerDocumentSchema, LedgerEdgeSchema } from "./ledger.gen";
import { EvidenceItemSchema, GraphRefSchema, OverlayDocumentSchema } from "./overlay.gen";

export type LedgerDocument = z.infer<typeof LedgerDocumentSchema>;
export type LedgerNode = LedgerDocument["nodes"][number];
export type LedgerEdge = z.infer<typeof LedgerEdgeSchema>;
export type OverlayDocument = z.infer<typeof OverlayDocumentSchema>;
export type EvidenceItem = z.infer<typeof EvidenceItemSchema>;
export type GraphRef = z.infer<typeof GraphRefSchema>;
export type DerivationDocument = z.infer<typeof DerivationDocumentSchema>;

export type LedgerTransactionNode = Extract<LedgerNode, { kind: "transaction" }>;
export type LedgerAddressNode = Extract<LedgerNode, { kind: "address" }>;
export type LedgerUnparsedNode = Extract<LedgerNode, { kind: "unparsed" }>;

/** One step of a derivation, with its children typed. */
export interface DerivationNode {
  id: string;
  kind: string;
  label: string;
  summary?: string | null;
  detail?: { key: string; kind: string; value?: string | number | boolean | string[] | null }[];
  value?: number | null;
  unit?: string | null;
  band?: string | null;
  /**
   * The generated `GraphRef`, not a copy of its shape. A second hand-written shape is one that can
   * drift from the schema the rest of the app is validated against — and the drift would be silent,
   * because a structural match is all TypeScript checks.
   */
  graph_refs?: GraphRef[];
  children?: DerivationNode[];
}

/**
 * Read a parsed derivation's root as a tree.
 *
 * The one cast in the app, and it is here because zod cannot express the recursive type. The
 * schema has already validated the shape — every field, at every depth — so this narrows a type
 * that is `unknown` for a reason unrelated to correctness.
 */
export function asTree(root: unknown): DerivationNode {
  return root as DerivationNode;
}

export { DerivationDocumentSchema, DerivationNodeSchema, LedgerDocumentSchema, OverlayDocumentSchema };

/** Which document a parsed JSON file turned out to be, or `null` if it is none of them. */
export function classify(
  value: unknown,
): { kind: "ledger"; document: LedgerDocument } | { kind: "overlay"; document: OverlayDocument } | { kind: "derivation"; document: DerivationDocument } | null {
  // Tried in order of specificity: a ledger document has `nodes` and `edges`, an overlay has
  // `by_node`, and a derivation has `root`. None is a subset of another, so the order does not
  // matter for correctness — but it does for the error a reader sees.
  const ledger = LedgerDocumentSchema.safeParse(value);
  if (ledger.success) return { kind: "ledger", document: ledger.data };

  const overlay = OverlayDocumentSchema.safeParse(value);
  if (overlay.success) return { kind: "overlay", document: overlay.data };

  const derivation = DerivationDocumentSchema.safeParse(value);
  if (derivation.success) return { kind: "derivation", document: derivation.data };

  return null;
}

export { isEvidenceItem };

/** Whether a value is an evidence item, for filtering a list that came from a document. */
function isEvidenceItem(value: unknown): value is EvidenceItem {
  return EvidenceItemSchema.safeParse(value).success;
}
