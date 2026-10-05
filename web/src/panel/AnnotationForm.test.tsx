/**
 * Recording an assertion: what the form refuses to send, and what it refuses to pretend.
 *
 * The rules that matter here are not about rendering. They are that the target is the selection
 * rather than something typed, that an assertion with no owner and no ground never leaves the
 * browser, and that a refused record is shown in the server's words and *kept* rather than cleared
 * along with the refusal.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AnnotationRequest, GraphRef } from "../schema/documents";
import { AnnotationRequestDocumentSchema } from "../schema/documents";
import { AnnotationForm } from "./AnnotationForm";

const TARGET: GraphRef = {
  kind: "node",
  key: "address:bitcoin:1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2",
  exists: null,
  note: null,
};

afterEach(() => {
  vi.restoreAllMocks();
});

function fill(values: Partial<Record<string, string>> = {}) {
  fireEvent.change(screen.getByLabelText("assertion"), {
    target: { value: values.assertion ?? "a venue deposit address" },
  });
  fireEvent.change(screen.getByLabelText("author"), { target: { value: values.author ?? "pm" } });
  fireEvent.change(screen.getByLabelText("basis"), {
    target: { value: values.basis ?? "listed on the venue's own deposit page" },
  });
  if (values.urls !== undefined) {
    fireEvent.change(screen.getByLabelText("URLs"), { target: { value: values.urls } });
  }
}

/**
 * What the form hands to the app, in the app's own signature.
 *
 * Named `OnRecord` rather than `Record`: the obvious name shadows TypeScript's own `Record<K, V>`
 * utility type, and silently breaks the first generic use of it in the file.
 */
type OnRecord = (request: AnnotationRequest) => Promise<string | null>;

function draw(writable: boolean, onRecord = vi.fn<OnRecord>(async () => null)) {
  const reason = writable ? null : "the server was started without an annotation directory";
  render(
    <AnnotationForm target={TARGET} writable={writable} reason={reason} onRecord={onRecord} />,
  );
  return onRecord;
}

describe("what the form sends", () => {
  it("sends the selection as the target, with nothing typed into it", async () => {
    const onRecord = draw(true);
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Record it" }));

    await waitFor(() => expect(onRecord).toHaveBeenCalledTimes(1));
    const sent = onRecord.mock.calls[0]![0];
    // `exists` is still null: the server resolves references, so a record claiming a lookup the
    // browser never made would be asserting something nobody checked.
    expect(sent.target).toEqual(TARGET);
    expect(sent.author).toBe("pm");
    expect(sent.basis).toMatch(/deposit page/);
    // And it is the shape the server validates against, checked before it leaves.
    expect(AnnotationRequestDocumentSchema.safeParse(sent).success).toBe(true);
  });

  it("splits the URL box into one field per line, dropping blanks", async () => {
    const onRecord = draw(true);
    fill({ urls: "https://example.test/a\n\n   \nhttps://example.test/b\n" });
    fireEvent.click(screen.getByRole("button", { name: "Record it" }));

    await waitFor(() => expect(onRecord).toHaveBeenCalledTimes(1));
    expect(onRecord.mock.calls[0]![0].evidence_urls).toEqual([
      "https://example.test/a",
      "https://example.test/b",
    ]);
  });

  it("trims whitespace rather than storing a field that is only spaces", async () => {
    const onRecord = draw(true);
    fill({ author: "  pm  " });
    fireEvent.click(screen.getByRole("button", { name: "Record it" }));
    await waitFor(() => expect(onRecord).toHaveBeenCalledTimes(1));
    expect(onRecord.mock.calls[0]![0].author).toBe("pm");
  });
});

describe("what the form refuses", () => {
  it("refuses a record with no basis, naming it, without asking the server", async () => {
    const onRecord = draw(true);
    fill({ basis: "" });
    fireEvent.click(screen.getByRole("button", { name: "Record it" }));

    expect(await screen.findByText(/needs .*the basis it rests on/)).toBeInTheDocument();
    // An assertion with no stated ground is not a record, so nothing was sent.
    expect(onRecord).not.toHaveBeenCalled();
  });

  it("refuses a record with no author, and names the assertion too when that is missing", async () => {
    const onRecord = draw(true);
    fill({ author: "", assertion: "" });
    fireEvent.click(screen.getByRole("button", { name: "Record it" }));
    const problem = await screen.findByText(/needs/);
    expect(problem.textContent).toMatch(/who is asserting it/);
    expect(problem.textContent).toMatch(/the assertion itself/);
    expect(onRecord).not.toHaveBeenCalled();
  });

  it("shows the server's refusal verbatim and keeps what was typed", async () => {
    // The return value is not used: what this test is about is what the *form* does with a
    // refusal, and the mock's own words are what it has to show.
    draw(
      true,
      vi.fn<OnRecord>(async () =>
        "an annotation must state the basis it rests on; an assertion with no stated ground is not a record",
      ),
    );
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Record it" }));

    // Not paraphrased: the server knows which constraint failed.
    expect(await screen.findByText(/an assertion with no stated ground is not a record/)).toBeInTheDocument();
    // And the text survives, so a refusal does not throw away the work as well as the record.
    expect((screen.getByLabelText("assertion") as HTMLTextAreaElement).value).toBe(
      "a venue deposit address",
    );
  });

  it("clears the assertion once it is recorded", async () => {
    draw(true);
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Record it" }));
    await waitFor(() =>
      expect((screen.getByLabelText("assertion") as HTMLTextAreaElement).value).toBe(""),
    );
    // The author and the basis are kept: the same person records several things in a row.
    expect((screen.getByLabelText("author") as HTMLInputElement).value).toBe("pm");
  });
});

describe("with nowhere to write", () => {
  it("says which of the two reasons it is, in the server's own words", () => {
    draw(false);
    expect(
      screen.getByText("the server was started without an annotation directory"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Record it" })).toBeNull();
  });

  it("offers the request as a file instead, and it is a request rather than a record", async () => {
    const created: Blob[] = [];
    vi.spyOn(URL, "createObjectURL").mockImplementation((blob) => {
      created.push(blob as Blob);
      return "blob:request";
    });
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    // jsdom has no `click`-to-download; the assertion is about what was handed to the browser.
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    draw(false);
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Download the request" }));

    expect(created).toHaveLength(1);
    const saved = JSON.parse(await created[0]!.text()) as Record<string, unknown>;
    // A request: what to record, without claiming an identifier or a time.
    expect(saved.target).toEqual(TARGET);
    expect(saved).not.toHaveProperty("id");
    expect(saved).not.toHaveProperty("created_at");
  });

  it("cannot download an empty request", () => {
    draw(false);
    expect(screen.getByRole("button", { name: "Download the request" })).toBeDisabled();
  });
});
