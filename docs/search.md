# Search syntax

Searches are meant to be typed the way you'd ask: *"why did the export get slow after the upgrade"*.
This page describes exactly what happens to what you type. The code is `search.py`.

## Words

1. **Words are split out** of the query, lower-cased (up to 24).
2. **Filler is dropped.** Common English words (*the, did, we, about, why, …*) and words that ask rather
   than describe (*look, show, find, search, tell, check, talk, discuss, remember, recall, thing, stuff,
   happen, please, want, need, …*) are removed. If nothing is left, the original words are used, so
   "where was it" still searches.
3. **Stemming.** Words are matched by their stem (Porter stemmer). *sampling*, *samples* and *sampled*
   all match each other. Accents are ignored.
4. **Any word can match.** The remaining words are OR'd together: a record needs at least one. Records
   with more of the words, rarer words, or the words in their title rank higher.

## Ranking

Matches are ranked with SQLite FTS5's **bm25**, over each record's title and body. Title matches count 3×.
What counts as the title and body:

| Record | Title | Body |
|---|---|---|
| Observation | title | subtitle, narrative, facts, concepts, text |
| Summary | the request | investigated, learned, completed, next steps, notes |
| Prompt | none | the prompt text |

The best **500** matches are kept for paging (2,000 when grouping by session). Sorting by date reorders
those same matches.

## Phrases: `"…"`

`"read only"` requires those words next to each other. They may be separated by punctuation, so
"read-only" matches. Phrases are checked against the text as written, not the stems, so `"read only"`
won't match "readings only". A record must contain every phrase in the query.

A query with only a phrase (and filler around it) searches for just the phrase: in `find "rate limit"`,
the word *find* is dropped.

## Exclusions: `-word`

`-redis` leaves out every record containing *redis* (by stem). Put the minus right before the word, after
a space or at the start.

## Typos

A word that's rare in your history also tries close spellings that are much more common there. The
alternatives are added to the search. The word you typed is never replaced, since the typo may well be
in your history too. The rules:

- The word must be 4+ letters, letters only, and appear in fewer than 50 records.
- A suggestion must be at least 20× as common (and in at least 3 records).
- It may differ by at most 1 letter edit for words up to 5 letters, or 2 edits for longer ones, and
  must be broadly similar overall.
- At most 3 alternatives per word.

So *beak* also tries *break*, *recieve* tries *receive*, and *incoding* tries *encoding*. A short word
that merely looks like a shifted common word (*caddy* vs *addition*) is left alone.

## Meaning search

With **Meaning** on, the query also goes to claude-mem's worker (`/api/search`). The worker returns the
records whose vector embeddings (Chroma) are closest in meaning, up to 50 of each kind. Those results go
through the same filters as yours: mode, project, type and hidden records. Then the two rankings are
merged by **reciprocal rank fusion**:

- score = Σ weight / (60 + rank), with word matches weighted 1.0 and meaning matches 0.5;
- a record found both ways adds both.

This lifts records that describe the same thing in other words, while keeping exact word matches on top.
The weights were tuned on a benchmark (see [How it works](how-it-works.md#benchmark)). Giving meaning
equal weight let it crowd out the right answer on misspelled queries, because only the word side knows
about typos.

Meaning search is **skipped** when:

- there's no query;
- Meaning is off;
- the query has a phrase or an exclusion, since those ask for exact matches.

Worker results are cached for 5 minutes per query, so paging doesn't ask again. If the worker takes
longer than 3 seconds or isn't running, results are word-only and the page says so.

## Highlighting

Matched words are highlighted in titles, in the matching passage shown under each result, and in opened
details. Highlighting is by stem, so searching *samples* also marks *sampling*.

## Tips

- Searching for a conversation rather than a single fact? Turn on **Group by session**.
- Too many loose matches? Use a `"phrase"`, pick a project, or switch to Conversation or Notes.
- Can't find it by words? Leave Meaning on and describe it differently. Or browse by date: clear the box
  and sort newest or oldest, with a project filter.
