/**
 * Recording an assertion about the selected node or edge.
 *
 * Five rules, each of which is the difference between a record and a remark:
 *
 * * **The target is the selection, and it is not typed.** A reader picks the node and then says
 *   what they know about it; a free-text key field would let a typo place evidence on a different
 *   address, which is the one mistake this panel could make that nobody would notice.
 * * **The author and the basis are required, and the form refuses locally before it sends.**
 *   `case-study/tools/verify.py` rejects a record with no stated ground for the same reason: an
 *   assertion with no basis is not a record. The refusal is local as well as server-side so a
 *   reader hears it while typing rather than after a round trip.
 * * **The payload is validated against the generated schema before it is sent** — the same
 *   contract the server validates against, so a field renamed in Python is a build failure here
 *   and not a 400 in the browser.
 * * **No write path exists when there is nowhere to write.** With no server, or a server started
 *   without an annotation directory, the form explains which of the two it is and offers the
 *   request as a file to keep instead. It never queues something that will not be recorded.
 * * **What the server says comes back verbatim.** A refused record is shown in the server's own
 *   words, because the server knows which constraint failed and this component does not.
 */
import { useState } from "react";

import { AnnotationRequestDocumentSchema } from "../schema/documents";
import type { AnnotationRequest, GraphRef } from "../schema/documents";

/** The kinds a person may assert, in the wire's own spelling. */
const KINDS = ["exchange", "mixer", "sanctioned", "own_wallet", "correction", "note"] as const;

export interface AnnotationFormProps {
  /** What the assertion is about: the reader's selection, never a typed key. */
  readonly target: GraphRef;
  /** Whether the server will take a record at all. */
  readonly writable: boolean;
  /** Why it will not, in the app's or the server's words. */
  readonly reason: string | null;
  /** Send it. Resolves with the server's own message when the record is refused. */
  readonly onRecord: (request: AnnotationRequest) => Promise<string | null>;
}

export function AnnotationForm({ target, writable, reason, onRecord }: AnnotationFormProps) {
  const [kind, setKind] = useState<(typeof KINDS)[number]>("note");
  const [assertion, setAssertion] = useState("");
  const [author, setAuthor] = useState("");
  const [basis, setBasis] = useState("");
  const [urls, setUrls] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const request = (): AnnotationRequest => ({
    // Passed through with `exists` still null, which is the truth rather than a default: the
    // server resolves a reference against the document it served, and the browser has made no
    // lookup to report. A record claiming `exists: true` would be asserting a check nobody ran.
    target,
    kind,
    assertion: assertion.trim(),
    author: author.trim(),
    basis: basis.trim(),
    evidence_urls: urls
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line !== ""),
  });

  const download = () => {
    const payload = JSON.stringify(request(), null, 2) + "\n";
    const href = URL.createObjectURL(new Blob([payload], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = href;
    link.download = "annotation-request.json";
    link.click();
    URL.revokeObjectURL(href);
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setProblem(null);
    const body = request();
    // The intent check comes first, and it is not the schema's job. The generated schema fixes the
    // *shape* — a string is a string, and an empty one validates — while an assertion with no
    // owner or no ground is a mistake about what a record is. The server refuses it too; hearing
    // it while typing is the difference between a form and a round trip.
    const missing = [
      body.author === "" ? "who is asserting it" : null,
      body.basis === "" ? "the basis it rests on" : null,
      body.assertion === "" ? "the assertion itself" : null,
    ].filter((item) => item !== null);
    if (missing.length > 0) {
      setProblem(`A record needs ${missing.join(", ")}.`);
      return;
    }
    const parsed = AnnotationRequestDocumentSchema.safeParse(body);
    if (!parsed.success) {
      setProblem(
        parsed.error.issues
          .map((issue) => `${issue.path.join(".") || "request"}: ${issue.message}`)
          .join("; "),
      );
      return;
    }
    setPending(true);
    const error = await onRecord(parsed.data);
    setPending(false);
    if (error !== null) {
      setProblem(error);
      return;
    }
    // Cleared only on success, so a refused record is not thrown away as well as refused.
    setAssertion("");
    setUrls("");
  };

  if (!writable) {
    return (
      <section className="annotate">
        <h3>Record an assertion</h3>
        <p className="hint">
          {reason ??
            "this server does not accept writes, so nothing can be recorded from here"}
        </p>
        <button type="button" onClick={download} disabled={assertion.trim() === ""}>
          Download the request
        </button>
        <p className="hint">
          The file holds what you typed, not a record: an identifier and a timestamp are stamped by
          whoever accepts it, so a saved request says what to record rather than claiming it was.
        </p>
        <Fields
          kind={kind}
          setKind={setKind}
          assertion={assertion}
          setAssertion={setAssertion}
          author={author}
          setAuthor={setAuthor}
          basis={basis}
          setBasis={setBasis}
          urls={urls}
          setUrls={setUrls}
        />
        {problem !== null && <p className="annotate-problem">{problem}</p>}
      </section>
    );
  }

  return (
    <section className="annotate">
      <h3>Record an assertion</h3>
      <form onSubmit={(event) => void submit(event)}>
        <Fields
          kind={kind}
          setKind={setKind}
          assertion={assertion}
          setAssertion={setAssertion}
          author={author}
          setAuthor={setAuthor}
          basis={basis}
          setBasis={setBasis}
          urls={urls}
          setUrls={setUrls}
        />
        <button type="submit" disabled={pending}>
          {pending ? "recording…" : "Record it"}
        </button>
      </form>
      {problem !== null && <p className="annotate-problem">{problem}</p>}
      <p className="hint">
        Written to the annotation directory this server was started with. It is your assertion, so
        it is recorded as yours and kept apart from anything the library computed.
      </p>
    </section>
  );
}

function Fields(props: {
  kind: (typeof KINDS)[number];
  setKind: (value: (typeof KINDS)[number]) => void;
  assertion: string;
  setAssertion: (value: string) => void;
  author: string;
  setAuthor: (value: string) => void;
  basis: string;
  setBasis: (value: string) => void;
  urls: string;
  setUrls: (value: string) => void;
}) {
  return (
    <>
      <label className="annotate-row">
        <span>kind</span>
        <select
          value={props.kind}
          onChange={(event) => props.setKind(event.target.value as (typeof KINDS)[number])}
        >
          {KINDS.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </label>
      <label className="annotate-row">
        <span>assertion</span>
        <textarea
          value={props.assertion}
          placeholder="what you are asserting about this, in your own words"
          onChange={(event) => props.setAssertion(event.target.value)}
        />
      </label>
      <label className="annotate-row">
        <span>author</span>
        <input
          value={props.author}
          placeholder="who is asserting it"
          onChange={(event) => props.setAuthor(event.target.value)}
        />
      </label>
      <label className="annotate-row">
        <span>basis</span>
        <textarea
          value={props.basis}
          placeholder="why you say so — an assertion with no stated ground is not a record"
          onChange={(event) => props.setBasis(event.target.value)}
        />
      </label>
      <label className="annotate-row">
        <span>URLs</span>
        <textarea
          value={props.urls}
          placeholder="one per line, anything a reader can go and look at"
          onChange={(event) => props.setUrls(event.target.value)}
        />
      </label>
    </>
  );
}
