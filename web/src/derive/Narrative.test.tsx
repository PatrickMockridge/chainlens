/**
 * The prose pane: what it shows, and the three states it has to tell apart.
 *
 * A narrative is the one thing in this app a model wrote, so the component's job is to keep that
 * visible — who wrote it, which steps each paragraph is about, and what was discarded getting there.
 * The state that matters most is the empty one: "a model wrote nothing usable" and "no model was
 * asked" are different facts, and a blank pane would let a reader take the first for the second.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { NarrativeDocument } from "../schema/documents";
import { Narrative } from "./Narrative";

function narrative(overrides: Partial<NarrativeDocument> = {}): NarrativeDocument {
  return {
    schema_version: 1,
    claim_id: "claim:abc",
    claim_quote: "carol moved ~30,000 sats to alice",
    verdict: "supported",
    paragraphs: [],
    style: "model",
    model: "claude-opus-5",
    prompt_version: 2,
    dropped: [],
    uncovered: [],
    limitations: "A verdict is about the match structure, not about belief.",
    generated_at: "2026-10-05T12:00:00Z",
    ...overrides,
  };
}

describe("a narrative", () => {
  it("names the model and the prompt that produced it", () => {
    render(<Narrative document={narrative()} />);
    expect(screen.getByText("claude-opus-5, prompt v2")).toBeInTheDocument();
  });

  it("renders each paragraph, with the steps it is about", () => {
    render(
      <Narrative
        document={narrative({
          paragraphs: [
            { text: "The claim was checked against the sender's history.", steps: ["claim/x"] },
            { text: "Nothing contradicted it.", steps: [] },
          ],
        })}
      />,
    );
    expect(screen.getByText(/checked against the sender/)).toBeInTheDocument();
    expect(screen.getByText(/about 1 step\(s\): claim\/x/)).toBeInTheDocument();
    // A paragraph about the argument as a whole says nothing about steps, rather than saying zero.
    expect(screen.getByText("Nothing contradicted it.")).toBeInTheDocument();
  });

  it("does not repeat the derivation's caveats, which are an inch above it", () => {
    // The document carries them so it can travel alone; in this pane the tree has already rendered
    // the same text, and printing it twice would train a reader to skip it.
    render(<Narrative document={narrative()} />);
    expect(screen.queryByText(/not about belief/)).toBeNull();
  });
});

describe("what it says about prose that was thrown away", () => {
  it("shows the discarded paragraphs and the reasons, rather than a shorter text", () => {
    render(
      <Narrative
        document={narrative({
          dropped: ["a paragraph used figure(s) the derivation does not contain (1905.16): '...'"],
        })}
      />,
    );
    expect(screen.getByText(/1 paragraph\(s\) were discarded rather than rewritten/)).toBeInTheDocument();
    expect(screen.getByText(/1905\.16/)).toBeInTheDocument();
  });

  it("says which steps have no prose, and that it is a gap rather than a disagreement", () => {
    render(<Narrative document={narrative({ uncovered: ["claim/x", "claim/y"] })} />);
    expect(screen.getByText(/2 step\(s\) of the derivation have no paragraph/)).toBeInTheDocument();
    expect(screen.getByText(/gap in the prose, not a disagreement/)).toBeInTheDocument();
  });

  it("distinguishes a model that wrote nothing from a model that was never asked", () => {
    const { unmount } = render(<Narrative document={narrative()} />);
    expect(screen.getByText(/nothing it wrote survived the checks/)).toBeInTheDocument();

    unmount();
    render(<Narrative document={narrative({ style: "none", model: null })} />);
    expect(screen.getByText(/No model was asked to write about this derivation/)).toBeInTheDocument();
    expect(screen.getByText("nothing written")).toBeInTheDocument();
  });
});
