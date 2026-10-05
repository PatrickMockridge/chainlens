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

import { AnnotationRequestDocumentSchema } from "./annotation_request.gen";
import { DerivationDocumentSchema, DerivationNodeSchema } from "./derivation.gen";
import { AnnotationSchema, LedgerDocumentSchema, LedgerEdgeSchema } from "./ledger.gen";
import { NarrativeDocumentSchema } from "./narrative.gen";
import { EvidenceItemSchema, GraphRefSchema, OverlayDocumentSchema } from "./overlay.gen";

export type LedgerDocument = z.infer<typeof LedgerDocumentSchema>;
/** Prose about one derivation, written by a model and checked against it before it was written. */
export type NarrativeDocument = z.infer<typeof NarrativeDocumentSchema>;
export type LedgerNode = LedgerDocument["nodes"][number];
export type LedgerEdge = z.infer<typeof LedgerEdgeSchema>;
export type OverlayDocument = z.infer<typeof OverlayDocumentSchema>;
export type EvidenceItem = z.infer<typeof EvidenceItemSchema>;
export type GraphRef = z.infer<typeof GraphRefSchema>;
export type DerivationDocument = z.infer<typeof DerivationDocumentSchema>;
/** A declared assertion, as an exported graph carries it. */
export type Annotation = z.infer<typeof AnnotationSchema>;
/**
 * What the app *sends* to record an annotation.
 *
 * The only wire type that travels towards the server, and it is generated for the same reason as
 * the rest: a payload written from a second description of the fields would be a second
 * description that can be wrong, and the browser would learn that from a 400. The record itself —
 * identifier and timestamp — is the server's to compose, which is why this type has neither.
 */
export type AnnotationRequest = z.infer<typeof AnnotationRequestDocumentSchema>;

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

export {
  AnnotationRequestDocumentSchema,
  DerivationDocumentSchema,
  DerivationNodeSchema,
  LedgerDocumentSchema,
  NarrativeDocumentSchema,
  OverlayDocumentSchema,
};

export type Classified =
  | { kind: "ledger"; document: LedgerDocument }
  | { kind: "overlay"; document: OverlayDocument }
  | { kind: "derivation"; document: DerivationDocument }
  | { kind: "narrative"; document: NarrativeDocument }
  | { kind: "request"; document: AnnotationRequest };

/** Which document a parsed JSON file turned out to be, or `null` if it is none of them. */
export function classify(value: unknown): Classified | null {
  // Tried in order of specificity: a ledger document has `nodes` and `edges`, an overlay has
  // `by_node`, and a derivation has `root`. None is a subset of another, so the order does not
  // matter for correctness — but it does for the error a reader sees.
  const ledger = LedgerDocumentSchema.safeParse(value);
  if (ledger.success) return { kind: "ledger", document: ledger.data };

  const overlay = OverlayDocumentSchema.safeParse(value);
  if (overlay.success) return { kind: "overlay", document: overlay.data };

  const derivation = DerivationDocumentSchema.safeParse(value);
  if (derivation.success) return { kind: "derivation", document: derivation.data };

  // A narrative has `claim_id` and `paragraphs`, neither of which any of the above carries.
  const narrative = NarrativeDocumentSchema.safeParse(value);
  if (narrative.success) return { kind: "narrative", document: narrative.data };

  // Last, because a request is the smallest of the five and the only one that is not a record of
  // anything: recognised so that dropping one back into the app explains what it is — a thing to
  // send to a server — rather than reporting an unrecognised file.
  const request = AnnotationRequestDocumentSchema.safeParse(value);
  if (request.success) return { kind: "request", document: request.data };

  return null;
}

export { isEvidenceItem };

/** Whether a value is an evidence item, for filtering a list that came from a document. */
function isEvidenceItem(value: unknown): value is EvidenceItem {
  return EvidenceItemSchema.safeParse(value).success;
}
