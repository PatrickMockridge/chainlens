/**
 * The prose about a derivation, rendered beside the argument it describes.
 *
 * Three things this refuses to do, each of them the reason it is a component rather than a
 * paragraph of JSX:
 *
 * * **it never hides an empty narrative.** "A model wrote nothing that survived the checks" and "no
 *   narrative was loaded" are different facts, and the first is not a blank — the discarded
 *   paragraphs and their reasons are shown, because a reader comparing this prose with the tree
 *   needs to know that something was thrown away.
 * * **it renders what was discarded, and which steps no paragraph covers.** A narrative that
 *   silently lost a sentence would read as complete, and a step nobody wrote about is a gap in the
 *   prose rather than a disagreement with the derivation.
 * * **it does not repeat the derivation's caveats.** The narrative document carries them so it can
 *   travel alone; here they are already on screen, an inch above, because the tree renders the same
 *   text. Printing them twice in one pane would train a reader to skip them.
 */
import type { NarrativeDocument } from "../schema/documents";

export interface NarrativeProps {
  document: NarrativeDocument;
}

export function Narrative({ document }: NarrativeProps) {
  const who = document.model ?? "nobody";
  return (
    <section className="narrative">
      <h3>
        Narrative
        <span className="badge">
          {document.style === "none" ? "nothing written" : `${who}, prompt v${document.prompt_version}`}
        </span>
      </h3>

      {document.paragraphs.length === 0 ? (
        <p className="hint">
          {document.style === "none"
            ? "No model was asked to write about this derivation, so nothing here is a judgement " +
              "on whether one should have been."
            : "A model wrote about this derivation and nothing it wrote survived the checks — " +
              "every paragraph carried a figure the derivation does not hold, or named a step it " +
              "does not contain. The reasons are below."}
        </p>
      ) : (
        document.paragraphs.map((paragraph, index) => (
          <p key={index} className="narrative-paragraph">
            {paragraph.text}
            {paragraph.steps.length > 0 && (
              <span className="narrative-steps">
                {" "}
                about {paragraph.steps.length} step(s): {paragraph.steps.join(", ")}
              </span>
            )}
          </p>
        ))
      )}

      {document.dropped.length > 0 && (
        <div className="narrative-dropped">
          <p className="hint">
            {document.dropped.length} paragraph(s) were discarded rather than rewritten — a figure
            the derivation does not hold, or a step it does not contain. A narrative with a silently
            missing sentence would read as complete.
          </p>
          <ul>
            {document.dropped.map((reason, index) => (
              <li key={index}>{reason}</li>
            ))}
          </ul>
        </div>
      )}

      {document.uncovered.length > 0 && (
        <p className="hint">
          {document.uncovered.length} step(s) of the derivation have no paragraph. That is a gap in
          the prose, not a disagreement with the argument.
        </p>
      )}
    </section>
  );
}
