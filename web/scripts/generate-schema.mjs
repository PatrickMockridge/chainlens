/**
 * Generate the zod schemas from the committed JSON Schema.
 *
 * The one hand-maintained description of the wire format is the pydantic models. Python emits
 * the JSON Schema from those, and this emits zod from the schema — so there is one artifact
 * anyone edits and two generated ones. Both are committed, and CI regenerates and diffs them,
 * which is what makes "a field added in Python without a matching TypeScript change" a red
 * build rather than a field that renders as `undefined` in a browser.
 *
 * **The generator does not resolve `$ref` itself.** `json-schema-to-zod` has no ref support at
 * any published version, and given a `$ref` it emits `z.any()` — a schema that validates
 * everything, which is worse than no schema because it looks like one. So refs are resolved
 * here, through the `parserOverride` hook, into *references to other generated schemas*:
 * `{"$ref": "#/$defs/LedgerEdge"}` becomes the identifier `LedgerEdgeSchema` rather than an
 * inlined copy. That keeps the names, which is what makes the output readable and what lets the
 * app write `z.infer<typeof LedgerEdgeSchema>` for the part it is working on.
 *
 * Named refs need every definition emitted before the definitions that use it, so the
 * definitions are topologically sorted over their ref graph.
 *
 * **`oneOf` is rewritten to `anyOf`.** The generator handles `anyOf` and not `oneOf`, and pydantic
 * emits a discriminated union as `oneOf` with a `discriminator` — three `$ref` arms keyed on a
 * `kind` literal. Because each arm pins that literal to a different constant, at most one arm can
 * ever match, so "at least one" and "exactly one" are the same condition for every payload this
 * contract can produce. Rewriting is therefore faithful rather than a loosening, and it is what
 * keeps the arms from collapsing to `z.any()`.
 *
 * **One definition is genuinely recursive** — `DerivationNode.children` is a list of
 * `DerivationNode` — so a strict ordering is impossible for it and it is emitted through
 * `z.lazy` instead, which defers the reference until parse time. Zod cannot infer the type of
 * a lazily-defined recursive schema, so those few carry an explicit `z.ZodType` annotation and
 * their inferred type is loose. The app casts once, where it walks the tree, and says why.
 * Their *validation* is complete; only the static type is weaker, and the property-key test
 * still holds their field set against the schema.
 */
import { readFileSync, readdirSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { jsonSchemaToZod } from "json-schema-to-zod";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const schemaDir = join(root, "schema");
const outDir = join(root, "src", "schema");
mkdirSync(outDir, { recursive: true });

/** Every `$ref` target named anywhere inside a schema fragment. */
function refsIn(node, found = new Set()) {
  if (Array.isArray(node)) {
    for (const item of node) refsIn(item, found);
  } else if (node && typeof node === "object") {
    if (typeof node.$ref === "string") {
      found.add(node.$ref.replace(/^#\/(?:\$defs|definitions)\//, ""));
    }
    for (const value of Object.values(node)) refsIn(value, found);
  }
  return found;
}

/** Rewrite `oneOf` to `anyOf` throughout, so the generator can see the arms. */
function anyOfInsteadOfOneOf(node) {
  if (Array.isArray(node)) return node.map(anyOfInsteadOfOneOf);
  if (!node || typeof node !== "object") return node;
  const rewritten = {};
  for (const [key, value] of Object.entries(node)) {
    rewritten[key] = anyOfInsteadOfOneOf(value);
  }
  if (Array.isArray(rewritten.oneOf) && rewritten.anyOf === undefined) {
    rewritten.anyOf = rewritten.oneOf;
    delete rewritten.oneOf;
  }
  return rewritten;
}

/** Whether a definition reaches itself, and so cannot be emitted in dependency order. */
function isRecursive(name, defs, seen = new Set()) {
  if (seen.has(name)) return true;
  seen.add(name);
  for (const ref of refsIn(defs[name])) {
    if (ref in defs && isRecursive(ref, defs, new Set(seen))) return true;
  }
  return false;
}

/** Definitions ordered so every non-recursive definition follows the ones it references. */
function sortDefinitions(defs) {
  const resolved = [];
  const done = new Set();

  const visit = (name) => {
    if (done.has(name)) return;
    done.add(name);
    for (const ref of refsIn(defs[name])) {
      // A recursive definition is deferred with `z.lazy`, so nothing needs to follow it.
      if (ref in defs && !isRecursive(ref, defs)) visit(ref);
    }
    resolved.push(name);
  };

  for (const name of Object.keys(defs)) visit(name);
  return resolved;
}

/**
 * Turn the generator's `const X = ...` into an exported declaration.
 *
 * A recursive definition is wrapped in `z.lazy` and annotated, because zod cannot infer the
 * type of a schema that refers to itself. The annotation is bare `z.ZodType` rather than a
 * parameter, which is the trade-off described at the top of this file.
 */
function exportDeclaration(emitted, identifier, recursive) {
  const body = emitted.replace(
    new RegExp(`^(?:export )?const ${identifier} = `),
    "",
  );
  if (recursive) {
    return `export const ${identifier}: z.ZodType = z.lazy(() => ${body.trimEnd()});`;
  }
  return `export const ${identifier} = ${body}`;
}

/** Emit `NameSchema` for a `$ref`, and let everything else fall through to the generator. */
function makeOverride() {
  return (schema) => {
    if (typeof schema.$ref === "string") {
      return `${schema.$ref.replace(/^#\/(?:\$defs|definitions)\//, "")}Schema`;
    }
    return undefined;
  };
}

/**
 * Every committed schema, read from the directory rather than listed here.
 *
 * **The list was a literal, and that made it a second description of the wire format.** The first
 * is `DOCUMENTS` in `chainlens/ledger/schema.py`; a document added there gets its `.schema.json`
 * from `make contract` and nothing compared the two lists. So a new document would commit
 * cleanly, have no zod module, and no test would say so — CI's drift check diffs `web/schema` and
 * the fixtures but not `web/src/schema`, where these modules land. Deriving the list removes the
 * second description rather than adding a third thing to keep in sync.
 */
const documents = readdirSync(schemaDir)
  .filter((file) => file.endsWith(".schema.json"))
  .map((file) => file.replace(/\.schema\.json$/, ""))
  .sort();

for (const name of documents) {
  const raw = JSON.parse(readFileSync(join(schemaDir, `${name}.schema.json`), "utf8"));
  const schema = anyOfInsteadOfOneOf(raw);
  const definitions = schema.$defs ?? schema.definitions ?? {};
  const order = sortDefinitions(definitions);

  const lines = [
    `// GENERATED FROM schema/${name}.schema.json -- DO NOT EDIT.`,
    "// Regenerate with `make contract`. A CI job regenerates and fails on a diff.",
    "",
    'import { z } from "zod";',
    "",
  ];

  for (const definition of order) {
    const { $defs, definitions: legacy, ...rootless } = definitions[definition];
    void $defs;
    void legacy;
    const identifier = `${definition}Schema`;
    const emitted = jsonSchemaToZod(rootless, {
      module: "none",
      name: identifier,
      zodVersion: 4,
      parserOverride: makeOverride(),
    });
    lines.push(exportDeclaration(emitted, identifier, isRecursive(definition, definitions)), "");
  }

  // The root last, since it references definitions rather than the other way round. Its own
  // `$defs` are dropped so the generator does not try to describe them as properties.
  const { $defs: rootDefs, definitions: rootLegacy, ...rootBody } = schema;
  void rootDefs;
  void rootLegacy;
  // Camel-cased from the file name, so `annotation_request` becomes `AnnotationRequest…` rather
  // than `Annotation_request…`: the identifier is what the app imports by name.
  const rootIdentifier = `${name
    .split(/[-_]/)
    .map((part) => `${part[0].toUpperCase()}${part.slice(1)}`)
    .join("")}DocumentSchema`;
  lines.push(
    exportDeclaration(
      jsonSchemaToZod(rootBody, {
        module: "none",
        name: rootIdentifier,
        zodVersion: 4,
        parserOverride: makeOverride(),
      }),
      rootIdentifier,
      false,
    ),
    "",
  );

  const contents = lines.join("\n");
  writeFileSync(join(outDir, `${name}.gen.ts`), contents, "utf8");
  console.log(
    `wrote src/schema/${name}.gen.ts: ${order.length} definitions + root, ${contents.length} bytes`,
  );
}
