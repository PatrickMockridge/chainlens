# `chainlens.social.capabilities`

The social layer's capability vocabulary.

One mechanism, two vocabularies. The decorator factory is
`chainlens.providers.capabilities.make_provides`, unchanged; what makes
this a *separate* vocabulary rather than an extension of
`chainlens.providers.capabilities.Capability` is the attribute name it
records onto. A class that is both a chain provider and a post source therefore
advertises two disjoint sets, and a chain capability cannot come into existence
because a method of the same name happened to be decorated here.

Why a source has to declare anything at all: asking a pasted post for its
thread is a reasonable question with an honest answer — "this source cannot do
that" — and a caller that cannot tell that from "the thread was empty" will
report a gap in the data as a fact about the world.

## `SocialCapability`

A discrete thing a post source can be asked to do.

**Members**

- `MANUAL` = 'post.manual'
- `POST_LOOKUP` = 'post.lookup'
- `POST_SEARCH` = 'post.search'
- `THREAD` = 'post.thread'

## `SOCIAL_PROVIDES_ATTR`

## `collect_social_capabilities`

```python
collect_social_capabilities(cls: type[Any]) -> frozenset[StrEnum]
```

Union the social capabilities declared across ``cls``'s MRO.

## `social_provides`
