/**
 * An annotation record, rendered as evidence — the projection an export needs and a live server
 * does not.
 *
 * A served graph gets its annotations through the overlay: Python joins the records onto the keys
 * the graph uses and hands over finished items. An *exported* graph has no server behind it, so it
 * carries the records themselves (`LedgerGraph.annotations`, inlined by `chainlens ui export`) and
 * the app has to reach the same rendering from the record.
 *
 * That makes this a second implementation of one small projection, which is exactly the kind of
 * thing that drifts. It is pinned instead of trusted: `annotations.test.ts` takes the *records*
 * from the committed fixture's annotated ledger and the *joined items* from the same fixture's
 * overlay — both produced by Python — and asserts this function turns the first into the second.
 * If either description of an annotation changes, that test fails.
 *
 * One detail is copied deliberately: `confidence` is null. An annotation has no confidence field —
 * a person may assert *what* an address is and never how sure the library should be — so a
 * declared item carries none, and the panel styles it apart.
 */
import type { Annotation, EvidenceItem } from "./schema/documents";

/** How a value is written into a `detail` row: the tagged-entry kinds the wire allows. */
type DetailKind = "string" | "bool" | "int" | "float" | "list";

function entry(key: string, kind: DetailKind, value: string | number | boolean | string[] | null) {
  return { key, kind, value, unit: null };
}

export function annotationEvidence(annotation: Annotation): EvidenceItem {
  // **Sorted by key**, matching `detail_entries` in `models/wire.py`. Insertion order is a
  // property of the mapping a writer happened to build, and the two routes to one annotation —
  // this projection and the server's join — would otherwise show the same facts in different
  // orders, which a reader would see as the panel rearranging itself between a live and a static
  // document.
  const rows: Record<string, ReturnType<typeof entry>> = {
    annotation_id: entry("annotation_id", "string", annotation.id),
    assertion: entry("assertion", "string", annotation.assertion),
    author: entry("author", "string", annotation.author),
    basis: entry("basis", "string", annotation.basis),
    created_at: entry("created_at", "string", annotation.created_at),
    evidence_urls: entry("evidence_urls", "list", [...annotation.evidence_urls]),
    kind: entry("kind", "string", annotation.kind),
    source: entry("source", "string", annotation.source),
  };
  return {
    kind: "annotation",
    // The words say "user-declared" as well as the styling, because the distinction has to
    // survive being separated from the panel that produced it — a copied JSON fragment, or a
    // screenshot of one node.
    summary: `user-declared ${annotation.kind}: ${annotation.assertion}`,
    detail: Object.keys(rows)
      .sort()
      .map((key) => rows[key]!),
    claim_id: null,
    // Empty, and deliberately: the overlay resolves an annotation's target against the document
    // it is joined onto and carries the resolved reference; here the record is filed *under* the
    // key it targets, so a reference back to that key would say nothing the filing did not.
    graph_refs: [],
    provenance: [],
    source: annotation.source,
    confidence: null,
  };
}

/** Where an annotation says it is about: the node or edge key it targets. */
export function targetKey(annotation: Annotation): string {
  return annotation.target.key;
}
