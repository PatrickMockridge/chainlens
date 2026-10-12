# Selection

The rule this corpus was collected under, and what it is a corpus *of*.

## The source

One public record: the United States' verified complaint for forfeiture in
***United States v. Approximately 127,271 BTC Previously Stored at the Virtual Currency Addresses
Listed in Attachment A*** (E.D.N.Y., 1:25-cv-05745), and its Exhibit A. Both were read from
`courtlistener.com`'s RECAP archive, are public filings, and are cited by URL on every record.

The complaint was chosen because it is the shape of document this pipeline is for: it states
**addresses with amounts**. Its Exhibit A is a schedule of property — twenty-five rows of
`N BTC at address A` — and its numbered paragraphs state dated movements, the largest of which the
text reads as *"the 3QL Wallet sent approximately 2,138.4 BTC to the 364 Wallet."*

## The unit

**One claim per address-and-amount the filing states** — a row of the schedule, or a dated sentence
of the complaint. Nothing else in the document is a claim, and the thirty records are what those two
forms yield.

Each record carries the sentence verbatim as its quote, so a reader can check what was read against
what the filing says. The quote is the span; the `[claim]` table below it is the extraction — the
addresses, the amount as written, and the reading this study applies to it.

## The readings, and why each is stated rather than inferred

Three things the filing does not say, and that a record has to:

- **a holding is about a past state.** Exhibit A states what was held when the schedule was filed, so
  each holding's window is the filing's date. The check then reports *a past holding* as a gap rather
  than comparing it to a balance read today — which is what it did before, and which contradicted
  every row of the schedule because the coins have since been seized.
- **a figure spanning a period is a total.** *"sent approximately 2,138.4 BTC between July 18 and
  September 30"* reads exactly like one payment and is, on chain, **262 of them**. Whether a sentence
  means one movement or a period's worth cannot be recovered from the sentence, so the record states
  it.
- **a sentence naming only a destination is a receipt.** *"13,469 newly minted BTC were sent to
  address 3QLeXx…"* names the recipient and not the payer, and is read on the arriving side. Before,
  the destination was taken for the sender and the claim was refuted with that address's spending.

## The provider

Every check was run against **`esplora-blockstream`**, named rather than left to the registry's
default. The default for bitcoin is `esplora-mempool`, and while this corpus was being built it took
seven seconds to return a single block height — so an eighty-page walk of a wallet's history timed
out, and every movement claim came back as *"the check did not complete"*. Both are the same Esplora
API and both are keyless; the name is recorded in every finding's provenance, and reproducing a
verdict needs the same one:

```console
make verify ARGS="--provider esplora-blockstream"
```

## No exclusions

Everything the two forms yield is a record. The tool that reads them **reports the paragraphs it
could not read** rather than passing over them — four of the complaint's dated paragraphs name no
address (`"sent through hosted wallets"`, `"from wallets at Exchange-1"`) and are listed in the
build's output, because a corpus that quietly dropped what it could not parse would look complete
and would not be.

## What a reader should conclude

Nothing about any person, and no support rate. The study's subject is **the pipeline**, and this
corpus is an adversarial input in the exact sense the README means: a real, formally pleaded set of
on-chain claims, written the way a court writes them, checked the way this library checks.
