/**
 * The annotation projection, pinned against Python's own rendering of the same record.
 *
 * An annotation reaches the app by two routes. A served graph sends the *join*: Python resolves
 * each record against the document and hands over a finished `EvidenceItem`. An exported graph
 * sends the *records*, because there is no server behind it, and this module is what turns one into
 * the other. Two implementations of one small projection, then — which is precisely the thing that
 * drifts, so it is pinned rather than trusted.
 *
 * The committed fixture carries both: `ledgers.annotated` holds the records, `overlays.bitcoin`
 * holds the join of the same three annotations, and both were produced by Python. So the
 * assertion below is not "the TypeScript agrees with itself" but "the TypeScript produces what
 * Python produces", for the identical input.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import type { Annotation, LedgerDocument, OverlayDocument } from "./schema/documents";
import { annotationEvidence, targetKey } from "./annotations";

const here = dirname(fileURLToPath(import.meta.url));
const fixtures = JSON.parse(
  readFileSync(join(here, "..", "..", "tests", "ledger", "fixtures", "graph-document.json"), "utf8"),
) as {
  ledgers: Record<string, LedgerDocument>;
  overlays: Record<string, OverlayDocument>;
};

const annotated = fixtures.ledgers["annotated"]!;
const overlay = fixtures.overlays["bitcoin"]!;

/** Every joined annotation item in the overlay, by the id it carries. */
function joinedById(): Map<string, Record<string, unknown>> {
  const found = new Map<string, Record<string, unknown>>();
  for (const where of ["by_node", "by_edge"] as const) {
    for (const items of Object.values(overlay[where] ?? {})) {
      for (const item of items) {
        if (item.kind !== "annotation") continue;
        const id = item.detail?.find((row) => row.key === "annotation_id")?.value;
        if (typeof id === "string") found.set(id, item as unknown as Record<string, unknown>);
      }
    }
  }
  return found;
}

describe("one annotation, two routes", () => {
  it("the fixture carries both, so this test can be about agreement", () => {
    // A guard on the fixture: if either half disappears the comparison below becomes vacuous.
    expect(annotated.annotations).toHaveLength(3);
    // Two of the three targets resolve; the third names an address outside the walk, and the
    // overlay reports that as a dangling *reference* rather than as an item (see below).
    expect(joinedById().size).toBe(2);
  });

  it("projects a record into exactly the item Python joined from it", () => {
    const joined = joinedById();
    const resolvable = (annotated.annotations ?? []).filter((record) => joined.has(record.id));
    expect(resolvable).toHaveLength(2);

    for (const record of resolvable) {
      const expected = joined.get(record.id);
      expect(expected, `no joined item for ${record.id}`).toBeDefined();
      const mine = annotationEvidence(record) as unknown as Record<string, unknown>;

      // Everything but the references, which is the one place the two routes differ and do: the
      // join resolves the record's target against the document it was joined onto, while this
      // projection files the record under the key it targets. Asserted separately below.
      expect(mine).toEqual({ ...expected, graph_refs: mine.graph_refs });
      expect(mine.kind).toBe("annotation");
      expect(mine.source).toBe("user");
      expect(mine.confidence).toBeNull();
    }
  });

  it("renders an assertion the join could not file anywhere", () => {
    // The third record targets an address the walk never reached. The overlay has no node key to
    // file it under — it reports a dangling reference instead, which is the right answer for a
    // structure keyed by node — while an exported document keeps the record and can still show
    // what was asserted. So the static path is, here, *more* informative than the live one, and
    // the assertion is that it says so rather than that the two agree.
    const joined = joinedById();
    const outside = (annotated.annotations ?? []).filter((record) => !joined.has(record.id));
    expect(outside).toHaveLength(1);

    const item = annotationEvidence(outside[0]!);
    expect(item.summary).toContain(outside[0]!.assertion);
    expect(item.source).toBe("user");
    // And the reference the join reported is the same key, so the two accounts of the same fact
    // name the same place.
    const reported = (overlay.unjoined ?? []).map((ref) => ref.key);
    expect(reported).toContain(targetKey(outside[0]!));
  });

  it("says user-declared in words, not only in styling", () => {
    const record = annotated.annotations![0]!;
    expect(annotationEvidence(record).summary).toMatch(/^user-declared \w+: /);
  });

  it("orders detail rows the way the wire does, so the panel cannot rearrange itself", () => {
    const record = annotated.annotations![0]!;
    const keys = (annotationEvidence(record).detail ?? []).map((row) => row.key);
    expect(keys).toEqual([...keys].sort());
  });

  it("differs from the join in exactly one way: the resolved reference", () => {
    const record = annotated.annotations!.find((item) =>
      targetKey(item).startsWith("address:"),
    )!;
    const expected = joinedById().get(record.id)!;
    const joinedRefs = expected.graph_refs as { key: string; exists: boolean | null }[];

    // The join marks the target present, which it can because it had the document in hand.
    expect(joinedRefs.map((ref) => [ref.key, ref.exists])).toEqual([[targetKey(record), true]]);
    // This projection carries none: the item is already filed under the key it is about.
    expect(annotationEvidence(record).graph_refs).toEqual([]);
  });
});

describe("the record itself", () => {
  it("has no field that could hold a measurement", () => {
    // The model-level rule, asserted here because this module is where a record becomes something
    // a panel renders: no confidence, no verdict, no amount.
    const record: Annotation = annotated.annotations![0]!;
    for (const forbidden of ["confidence", "verdict", "amount", "lr", "scale"]) {
      expect(record).not.toHaveProperty(forbidden);
    }
  });
});
