# Contributing

Issues and pull requests are welcome. Bug reports are most useful with:

- the server's output;
- your OS, Python and claude-mem versions;
- the query that misbehaved, if it's safe to share.

**Never paste content from your own history** into an issue. And please report security problems
privately, through the repo's
[security advisories](https://github.com/NarlySoftware/claude-mem-history-search/security/advisories/new).

## Ground rules

- **Never write to claude-mem's database.** It belongs to claude-mem's worker, which writes to it
  constantly. Open it only through `indexer.connect_source()` / `server.connect()`: read-only, with
  `query_only`.
- **Standard library only** for Python (3.9+), and no build step or dependencies for the page.
- **Keep it local.** Don't add anything that binds beyond `127.0.0.1`, loads resources from the
  internet, or sends data anywhere other than claude-mem's own worker.
- **Search changes must not lower the benchmark** on your own history (below). Say in the pull request
  how the scores moved.
- Match the surrounding code: short functions, comments that say *why*, plain names.

## Tests

```sh
python3 -I tests/test_search.py     # index and ranked search
python3 -I tests/test_api.py        # server, paging, escaping, filters, access rules
```

By default the tests build a small made-up claude-mem database (`tests/fixture.py`) in a temporary
folder, and use a stand-in worker where meaning search is tested. They run the same on any machine and
don't touch your data or `data/`. To run them against your real database and worker as well
(read-only):

```sh
HISTORY_SEARCH_TESTS=live python3 -I tests/test_search.py
HISTORY_SEARCH_TESTS=live python3 -I tests/test_api.py
```

Please run both, under the oldest Python you can (macOS's `/usr/bin/python3` is 3.9).

## Trying the page without your own history

`tests/demo.py` builds a demo database of invented sessions (the one in the screenshots):

```sh
python3 -I tests/demo.py /tmp/demo.db
HISTORY_SEARCH_INDEX=/tmp/demo-index.db HISTORY_SEARCH_LOCAL=/dev/null CLAUDE_MEM_WORKER_PORT=9 \
  python3 -I server.py --db /tmp/demo.db --port 37691
```

`CLAUDE_MEM_WORKER_PORT=9` points meaning search at nothing, so it doesn't mix in ids from your real
worker.

## Phone and screenshots

`tests/phone.mjs` checks the page in WebKit with Playwright's iPhone 13 profile:

- nothing wider than the screen;
- inputs at least 16 px (so iOS doesn't zoom);
- the search box, session view, back navigation and grouping work.

`tests/screenshots.mjs` regenerates `docs/img/` from the demo server. Both need Playwright, installed
outside the repo; the commands are at the top of each file. Run the phone check for any change to
`index.html`.

## Benchmark

`bench/run.py` scores search quality on queries about **your own** records:

- hit@1 and hit@10, for the exact record and for any record from its session;
- MRR (reciprocal rank).

No queries ship with the code, since they would quote someone's history. Write
`bench/queries.json` like this:

```json
{"queries": [
  {"id": "q1", "style": "exact", "query": "jwt leeway clock skew",
   "target": {"kind": "observation", "id": 1234}},
  {"id": "q2", "style": "concept", "query": "why did people keep getting signed out",
   "target": {"kind": "observation", "id": 1234}}
]}
```

- `style` groups the scores. Writing both an `exact` and a `concept` (described differently) query for
  each target works well.
- `target` is a record id in claude-mem's database: `observations`, `session_summaries` or
  `user_prompts`, by `kind`.

```sh
python3 -I bench/run.py --engine ranked            # words only (fast)
python3 -I bench/run.py --engine hybrid            # + meaning, as the page searches (needs the worker)
python3 -I bench/run.py --engine grouped --show-misses
```

Engines: `baseline` (the old every-word search), `ranked`, `hybrid`, `semantic` (worker only) and
`grouped`. This project's own records are left out, since sessions about the benchmark would leak
answers.

## Docs

User-facing behaviour is documented in `docs/`. Update the matching page in the same pull request, and
the API page for any change to a response.
