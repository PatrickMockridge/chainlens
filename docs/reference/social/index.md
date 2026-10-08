# `chainlens.social`

Post ingest.

The social layer turns a post — fetched, resolved, pasted or screenshotted — into
a normalized, hashable record that the verification layer can work from. It
concludes nothing about a post's content: that is what the chain data is for, and
keeping the two apart is the property the rest of the design serves.

Two things every model here is careful about, because they are the two ways this
layer can mislead:

* **How the content arrived is not how good the content is.** Provenance strength
  is recorded and rendered separately from any finding, so a claim inside a
  screenshot cannot inherit the credibility of an API response — or lose the
  credibility of the chain data inside it.
* **A post is editable.** A capture is only meaningful next to a record of what it
  said, which is why every post carries a content hash over exactly the parts its
  author can change.
