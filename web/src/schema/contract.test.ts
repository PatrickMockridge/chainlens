/**
 * The contract test: the generated schemas against the documents Python actually produced.
 *
 * Two mechanisms, and neither alone is enough.
 *
 * **The golden fixtures** are validated here, so a schema that has drifted from real output fails
 * immediately. But a fixture only pins the fields it happens to *contain*: a new optional field
 * added in Python would not appear in any fixture, and a fixture-only check would pass.
 *
 * **The property-key manifest check** closes that hole. For every object in the committed JSON
 * Schema, the corresponding zod object's key set must equal the schema's `properties` key set —
 * so presence is checked independently of whether any sample carries the field. That is the check
 * that makes "add a field to a pydantic model" fail here rather than render as `undefined`.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  LedgerAddressNodeSchema,
  LedgerEdgeSchema,
  LedgerTransactionNodeSchema,
  LedgerDocumentSchema,
} from "./ledger.gen";
import {
  DerivationDocumentSchema,
  DerivationNodeSchema,
} from "./derivation.gen";
import { EvidenceItemSchema, OverlayDocumentSchema } from "./overlay.gen";
import { AnnotationRequestDocumentSchema } from "./annotation_request.gen";
import { NarrativeDocumentSchema } from "./narrative.gen";

const here = dirname(fileURLToPath(import.meta.url));
const repo = join(here, "..", "..", "..");

function readJson(path: string): Record<string, unknown> {
  return JSON.parse(readFileSync(path, "utf8")) as Record<string, unknown>;
}

const fixtures = readJson(
  join(repo, "tests", "ledger", "fixtures", "graph-document.json"),
);
const schemas = {
  ledger: readJson(join(here, "..", "..", "schema", "ledger.schema.json")),
  derivation: readJson(
    join(here, "..", "..", "schema", "derivation.schema.json"),
  ),
  overlay: readJson(join(here, "..", "..", "schema", "overlay.schema.json")),
} as const;

type Family = Record<string, unknown>;

// --------------------------------------------------------------------------- #
// The fixtures Python produced
// --------------------------------------------------------------------------- #
describe("the fixtures Python produced", () => {
  // **Five families, and two of them were missing.** `narrative` was in the fixture and
  // validated by nobody, and `annotation_request` had a generated schema and no committed
  // example at all — so a schema describing a shape Python had stopped producing would have
  // kept reporting green on this side. The Python half notices that now too; see
  // `test_every_document_kind_has_a_committed_example`.
  const cases: [string, Family, { parse: (value: unknown) => unknown }][] = [
    ["ledgers", fixtures["ledgers"] as Family, LedgerDocumentSchema],
    [
      "derivations",
      fixtures["derivations"] as Family,
      DerivationDocumentSchema,
    ],
    ["overlays", fixtures["overlays"] as Family, OverlayDocumentSchema],
    ["narratives", fixtures["narratives"] as Family, NarrativeDocumentSchema],
    [
      "annotation_requests",
      fixtures["annotation_requests"] as Family,
      AnnotationRequestDocumentSchema,
    ],
  ];

  for (const [family, documents, schema] of cases) {
    it(`validates every ${family} document`, () => {
      expect(Object.keys(documents).length).toBeGreaterThan(0);
      for (const [name, document] of Object.entries(documents)) {
        expect(() => schema.parse(document), `${family}.${name}`).not.toThrow();
      }
    });
  }

  it("covers every node kind the graph can hold", () => {
    const kinds = new Set<string>();
    for (const document of Object.values(fixtures["ledgers"] as Family)) {
      for (const node of (document as { nodes: { kind: string }[] }).nodes)
        kinds.add(node.kind);
    }
    expect(kinds).toEqual(new Set(["address", "transaction", "unparsed"]));
  });

  it("carries a derivation in each shape", () => {
    const shapes = new Set(
      Object.values(fixtures["derivations"] as Family).map(
        (document) => (document as { has_ratio: boolean }).has_ratio,
      ),
    );
    expect(shapes).toEqual(new Set([true, false]));
  });

  it("carries evidence that did not resolve, because reporting it is the point", () => {
    for (const document of Object.values(fixtures["overlays"] as Family)) {
      const unjoined = (document as { unjoined: { exists: boolean }[] })
        .unjoined;
      expect(unjoined.length).toBeGreaterThan(0);
      expect(unjoined.every((ref) => ref.exists === false)).toBe(true);
    }
  });
});

// --------------------------------------------------------------------------- #
// Strictness, which is the property fixtures cannot give
// --------------------------------------------------------------------------- #
describe("strictness", () => {
  const document = Object.values(fixtures["ledgers"] as Family)[0] as Record<
    string,
    unknown
  >;

  it("refuses a key the models do not have", () => {
    expect(() =>
      LedgerDocumentSchema.parse({ ...document, sneaked: 1 }),
    ).toThrow();
  });

  it("refuses a key inside a node, not only at the root", () => {
    const nodes = structuredClone(
      (document as { nodes: unknown[] }).nodes,
    ) as Record<string, unknown>[];
    nodes[0] = { ...nodes[0], sneaked: 1 };
    expect(() => LedgerDocumentSchema.parse({ ...document, nodes })).toThrow();
  });

  it("refuses a node whose kind is not one the contract names", () => {
    expect(() =>
      LedgerAddressNodeSchema.parse({
        key: "k",
        chain: "bitcoin",
        kind: "widget",
      }),
    ).toThrow();
  });
});

// --------------------------------------------------------------------------- #
// The property-key manifest check
// --------------------------------------------------------------------------- #
type ZodObjectish = {
  shape?: Record<string, unknown>;
  def?: { getter?: () => unknown };
};

/**
 * The generated schema for a definition, by the name the generator emits.
 *
 * A recursive definition is emitted through `z.lazy`, which has no `shape` of its own — so it is
 * unwrapped through its getter. Without that the key-set check would silently skip exactly the
 * definition that is most likely to drift, and a check that skips is worse than one that fails
 * because it still reports green.
 */
function schemaFor(definition: string): ZodObjectish | undefined {
  const registry: Record<string, unknown> = {
    LedgerAddressNode: LedgerAddressNodeSchema,
    LedgerTransactionNode: LedgerTransactionNodeSchema,
    LedgerEdge: LedgerEdgeSchema,
    DerivationNode: DerivationNodeSchema,
    EvidenceItem: EvidenceItemSchema,
  };
  const found = registry[definition] as ZodObjectish | undefined;
  if (found === undefined) return undefined;
  if (found.shape !== undefined) return found;
  const unwrapped = found.def?.getter?.() as ZodObjectish | undefined;
  return unwrapped?.shape !== undefined ? unwrapped : undefined;
}

describe("every field the schema describes exists in the generated type", () => {
  const definitions = (schemas.ledger["$defs"] ?? {}) as Record<
    string,
    { properties?: object }
  >;

  it("has a zod object for a representative definition", () => {
    // Guards the check itself: if the registry stopped resolving, the assertions below would
    // vacuously pass over an empty list.
    expect(Object.keys(definitions).length).toBeGreaterThan(5);
    expect(schemaFor("LedgerEdge")).toBeDefined();
  });

  for (const definition of [
    "LedgerAddressNode",
    "LedgerTransactionNode",
    "LedgerEdge",
  ]) {
    it(`${definition} has exactly the fields the schema names`, () => {
      const zod = schemaFor(definition);
      const declared = Object.keys(definitions[definition]?.properties ?? {});
      expect(declared.length).toBeGreaterThan(0);
      expect(Object.keys(zod?.shape ?? {}).sort()).toEqual(declared.sort());
    });
  }

  it("DerivationNode has exactly the fields the schema names", () => {
    const derivationDefs = (schemas.derivation["$defs"] ?? {}) as Record<
      string,
      { properties?: object }
    >;
    const declared = Object.keys(
      derivationDefs["DerivationNode"]?.properties ?? {},
    );
    expect(declared.length).toBeGreaterThan(0);
    expect(
      Object.keys(schemaFor("DerivationNode")?.shape ?? {}).sort(),
    ).toEqual(declared.sort());
  });

  it("EvidenceItem has exactly the fields the schema names", () => {
    const overlayDefs = (schemas.overlay["$defs"] ?? {}) as Record<
      string,
      { properties?: object }
    >;
    const declared = Object.keys(overlayDefs["EvidenceItem"]?.properties ?? {});
    expect(declared.length).toBeGreaterThan(0);
    expect(Object.keys(schemaFor("EvidenceItem")?.shape ?? {}).sort()).toEqual(
      declared.sort(),
    );
  });

  it("the root document has exactly the fields the schema names", () => {
    const declared = Object.keys(
      (schemas.ledger["properties"] ?? {}) as object,
    );
    expect(Object.keys(LedgerDocumentSchema.shape).sort()).toEqual(
      declared.sort(),
    );
  });
});

// --------------------------------------------------------------------------- #
// The recursive node
// --------------------------------------------------------------------------- #
describe("the recursive derivation node", () => {
  it("validates a tree nested several levels deep", () => {
    const leaf = { id: "leaf", kind: "caveat", label: "a caveat" };
    const branch = {
      id: "b",
      kind: "claim",
      label: "a claim",
      children: [leaf],
    };
    const root = {
      id: "root",
      kind: "claim",
      label: "the root",
      children: [branch],
    };

    const parsed = DerivationNodeSchema.parse(root) as {
      children: { children: unknown[] }[];
    };
    expect(parsed.children[0]?.children).toHaveLength(1);
  });

  it("refuses a nested node the contract does not describe", () => {
    const root = {
      id: "root",
      kind: "claim",
      label: "x",
      children: [{ id: "bad" }],
    };
    expect(() => DerivationNodeSchema.parse(root)).toThrow();
  });
});
