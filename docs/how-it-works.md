# How it works

```
claude-mem.db (read-only) ──► indexer.py ──► data/index.db (FTS5, ours)
                                                  │
browser ◄── index.html ◄── server.py ◄── search.py ┤
                              127.0.0.1           └──► claude-mem worker /api/search (meaning, optional)
```

| File | |
|---|---|
| `server.py` | HTTP server (standard library), access checks, the API, and a background thread that keeps the index current |
| `search.py` | Query parsing, ranking, typo handling, meaning fusion, grouping, the session view |
| `indexer.py` | Builds and tops up our index from claude-mem's database; hiding rules; start-up checks |
| `config.py` | Finds claude-mem's data folder, database and worker the way claude-mem does |
| `index.html` | The whole page: HTML, CSS and plain JavaScript, no build step and no external resources |

## Why its own index

claude-mem has full-text tables and a search API of its own, so why build another index?

- **Ranking across kinds.** Questions are better answered by ranking observations, summaries and
  prompts together by relevance (bm25, stemmed, titles weighted) than by date. claude-mem's full-text
  tables don't cover prompts, and they aren't stemmed.
- **Exact totals for paging.** First / Last and go-to-page need a total count. The worker's API returns
  only "has more".
- **Typo tolerance** needs the index's vocabulary.
- **Speed.** A ranked query over ~55,000 records takes tens of milliseconds.

The index is one table holding every observation, summary and prompt as a title and body, with an FTS5
index (Porter stemming, accents ignored). It's about 2.5 KB per record (≈140 MB for 55,000) and takes
about 3 seconds to build.

The server tops the index up every 10 seconds. New records are simply appended. A full rebuild happens
when:

- records were deleted;
- claude-mem merged projects;
- the hiding rules in `local.json` changed;
- an update changed the index layout.

`data/` is safe to delete at any time: it's rebuilt on the next start. To refresh it by hand, run
`python3 -I indexer.py [--rebuild]`.

## Meaning search

claude-mem's worker keeps vector embeddings of your records in Chroma and offers a search over them. This
tool asks that search for each query and merges the results with its own word ranking, as described in
[Search syntax](search.md#meaning-search). It doesn't run a model or hold vectors itself. If the worker
isn't running, or Chroma is turned off, searches fall back to words only.

## Privacy and security

Your claude-mem database holds complete prompts and notes from all your sessions, possibly including
secrets you pasted. The design keeps that on your machine:

- **Read-only.** claude-mem's database is opened with SQLite's `mode=ro` and `PRAGMA query_only`, so the
  connection can't write even by mistake. The tests check this. The worker's search API is read-only
  too: checked by comparing table row counts before and after.
- **Local only.** The server binds `127.0.0.1`, never all interfaces.
- **Host check.** Requests must name `localhost` or `127.0.0.1` as their `Host`. This stops a web page on
  another site from reading the API through DNS rebinding.
- **Tailscale check.** A request for a `*.ts.net` name (which arrives through `tailscale serve`) is
  served only if Tailscale's `Tailscale-User-Login` header is your own login, or one allowed with
  `--allow-user`. Tailscale sets that header itself for tailnet traffic. Tagged machines and machines
  shared in from other tailnets carry no matching login, so they get 403.
- **No outside requests.** The page loads nothing from the internet. The server's only outgoing calls
  are to claude-mem's worker, at the address claude-mem itself is configured with, and to the local
  `tailscale` command at start-up to read your login.
- **No caching.** Responses are sent with `Cache-Control: no-store`.
- **Output is escaped.** Everything from the database is HTML-escaped before it's shown. Search input is
  passed to SQLite as parameters, never pasted into SQL. FTS syntax in queries is neutralised by quoting
  each term.

What it doesn't do:

- There are no passwords or user accounts. Anyone who can reach `127.0.0.1` on your machine as your
  user, or as another local user, can use it. That's the same exposure as your claude-mem database
  file, which they could read directly.
- Don't run it on a shared machine where you don't trust the other local users.
- Don't expose it with `--host 0.0.0.0` (there's no such option, on purpose), a reverse proxy or
  Tailscale Funnel.

Found a security problem? Please report it privately through GitHub's
[security advisories](https://github.com/NarlySoftware/claude-mem-history-search/security/advisories/new)
rather than a public issue.

## Performance

Measured on a history of ~55,000 records on an Apple-silicon Mac:

| | |
|---|---|
| Word search or browse, one page of 25 with details | ~20–60 ms (the first search after a start, ~0.3 s, loads the vocabulary) |
| Meaning search (worker round trip) | ~0.5 s; cached 5 min per query |
| Session view | ~2 ms; ~25 ms for a session with thousands of records |
| Full index build | ~3 s |

## Benchmark

Search quality was measured with `bench/run.py` against 94 known-item queries on the author's own
history. Each query targets one record. "Session hit@10" counts a success if any record from the right
session is in the top 10 results.

| Queries | Old search (all words, newest first) | Ranked words | + meaning | Grouped by session |
|---|---|---|---|---|
| Exact wording (42) | 100% | 100% | 100% | 100% |
| Described differently (42) | 7% | 69% | 71% | 86% |
| Written blind by the user (10) | 20% | 100% | 100% | 100% |

The remaining misses share almost no words with their target, and the worker's vectors don't bridge
them either. The queries aren't published, since they quote private history. To score your own, see
[Contributing](../CONTRIBUTING.md#benchmark).

## Limits

- **claude-mem versions:** developed against claude-mem 13.40. It reads a handful of tables and columns,
  and checks for them at start-up. A schema change in claude-mem could still break it.
- **Platforms:** macOS is used daily. Linux should work but is untested. Windows is untested; the code
  has no deliberate Windows support beyond the worker-port fallback.
- **Assistant replies:** claude-mem doesn't store the assistant's replies word for word, only per-turn
  summaries and observations. So this tool can't search the replies themselves.
- **Ranking cap:** a query keeps its best 500 matches (2,000 grouped). Very broad queries are better
  narrowed than paged through.
- **Meaning search** depends on claude-mem's worker and its Chroma index. Its results are limited to the
  worker's top 50 per record kind.
