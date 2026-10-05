/**
 * The prose about a derivation, rendered beside the argument it describes.
 *
 * **The citations are clickable, and that is the point of putting the prose here.** A paragraph
 * that says "about 3 step(s): …" is making a claim about the derivation, and a reader can check it:
 * clicking a step opens it as the current branch, which highlights it in the tree and its ledger
 * keys in the graph — the same selection a click in the tree would make, so the panes stay one
 * instrument rather than two. Without this the prose would be the only part of this screen a reader
 * had to take on trust.
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
  /** Open a step as the current branch: what a click in the tree does, so the two agree. */
  onSelectStep: (stepId: string) => void;
  /** Whether the derivation actually holds a step, so a citation can say when it does not. */
  holds: (stepId: string) => boolean;
}

export function Narrative({ document, onSelectStep, holds }: NarrativeProps) {
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
          {/*
            Three states, not two. "Nobody asked", "a model was asked and wrote nothing", and "a
            model wrote and every paragraph was discarded" are different facts about the same empty
            box, and a pane that said one of them in all three cases would be lying twice.
          */}
          {document.style === "none"
            ? "No model was asked to write about this derivation, so nothing here is a judgement " +
              "on whether one should have been."
            : document.dropped.length === 0
              ? "A model was asked and wrote nothing. That is an empty answer rather than a " +
                "rejected one — nothing was discarded, because there was nothing to discard."
              : "A model wrote about this derivation and nothing it wrote survived the checks — " +
                "every paragraph carried a figure the derivation does not hold, or named a step " +
                "it does not contain. The reasons are below."}
        </p>
      ) : (
        document.paragraphs.map((paragraph, index) => (
          <p key={index} className="narrative-paragraph">
            {paragraph.text}
            {paragraph.steps.length > 0 && (
              <span className="narrative-steps">
                {" "}
                about {paragraph.steps.length} step(s):{" "}
                {paragraph.steps.map((stepId) => (
                  <button
                    key={stepId}
                    type="button"
                    className="step-chip"
                    onClick={() => onSelectStep(stepId)}
                  >
                    {stepId}
                  </button>
                ))}
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
          {document.uncovered.length} step(s) of the derivation have no paragraph:{" "}
          {/* Named and clickable, because a gap a reader can look at is a gap they can judge —
              and a step the prose skipped is exactly the thing worth checking. */}
          {document.uncovered.map((stepId) => (
            <button
              key={stepId}
              type="button"
              className={`step-chip${holds(stepId) ? "" : " ref-absent"}`}
              title={holds(stepId) ? "open this step" : "not in this derivation"}
              onClick={() => onSelectStep(stepId)}
            >
              {stepId}
            </button>
          ))}{" "}
          That is a gap in the prose, not a disagreement with the argument.
        </p>
      )}
    </section>
  );
}
