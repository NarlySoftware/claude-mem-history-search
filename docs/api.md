# API

Everything the page shows comes from a small JSON API on the same server. You can call it too, from
scripts or other tools. Every endpoint is `GET` and read-only. The same access rules as the page apply:
`localhost` / `127.0.0.1`, or your own login through Tailscale.

Errors:

- `400` with `{"error": "…"}` for a bad parameter, e.g. `page=abc`;
- `403` (plain text) for a refused host or login;
- `404` for an unknown path or session.

## `GET /api/find`: search or browse

| Parameter | Default | |
|---|---|---|
| `q` | empty | The query ([syntax](search.md)). Empty browses everything. |
| `mode` | `everything` | `conversation`, `notes` or `everything` |
| `project` | all | A project name (also matches records merged into it) |
| `type` | all | An observation type (`discovery`, `change`, `feature`, `bugfix`, `decision`, `refactor`) or `other`; limits results to observations |
| `sort` | `best` with a query, `newest` without | `best`, `newest` or `oldest` |
| `size` | 25 | Results per page, 5–100 |
| `page` | 1 | Page number; `-1` is the last page; past the end gives the last page |
| `meaning` | `1` | `0` turns off meaning search |
| `group` | `0` | `1` pages through sessions instead of records |

```sh
curl -s 'http://localhost:37690/api/find?q=export+slow&mode=notes&size=5' | python3 -m json.tool
```

Response:

| Field | |
|---|---|
| `mode`, `sort`, `size`, `page`, `pages` | As applied (invalid values fall back to defaults) |
| `total` | Matching records (or sessions when grouped). With a query, at most 500 (2,000 grouped). |
| `capped` | `true` if a query hit that limit |
| `first_index` | Position of the first result on this page (1-based), 0 if none |
| `semantic` | `true`: meaning results were merged in; `false`: the worker was unavailable, so the results are word-only; `null`: not used |
| `terms` | Stems to highlight |
| `query` | How the query was read: `{"words": […], "phrases": […], "excludes": […]}` |
| `items` | The results (below). Empty when grouped. |
| `grouped`, `groups` | With `group=1`: `true`, and a list of sessions (below) |

Each item:

| Field | |
|---|---|
| `kind` | `observation`, `summary` or `prompt` |
| `src_id` | The record's id in claude-mem's database (its table depends on `kind`) |
| `rowid` | Its id in our index |
| `project`, `session`, `platform_source` | Project, claude-mem memory session id, and the tool that recorded it (`claude`, …) |
| `type` | Observation type; `agent` for subagent messages recorded as prompts |
| `created_at_epoch` | Milliseconds since 1970 |
| `title` | Title (observations), request (summaries), none for prompts |
| `title_hl`, `snippet` | With a query: the title and best-matching passage, with matches between `\u0002` and `\u0003` |
| `detail` | The full record from claude-mem's database: `prompt_number` plus, for observations, `title`, `type`, `subtitle`, `narrative`, `facts`, `files_read`, `files_modified`; for summaries, `request`, `investigated`, `learned`, `completed`, `next_steps`, `notes`, `files_edited`; for prompts, `prompt_text`. List fields are JSON strings, as claude-mem stores them. |

Each group (with `group=1`):

| Field | |
|---|---|
| `session` | Memory session id (`null` for a record without one) |
| `project` | The project of its first match |
| `matches` | Matches in this session (records, when browsing) |
| `first_epoch`, `last_epoch` | Time span of those matches |
| `items` | Up to 3 of them, in the chosen order, shaped like the items above |

## `GET /api/session`: one session, by turn

| Parameter | Default | |
|---|---|---|
| `session` | required | Memory session id, as in `items[].session` |
| `turn` | first turn | The turn to centre on (if it has no records, the nearest later one) |
| `before`, `after` | 2, 2 | How many turns to include on each side (up to 200) |

Response:

| Field | |
|---|---|
| `session`, `project`, `platform_source` | |
| `first_epoch`, `last_epoch` | Time span of the session's visible records |
| `turn_numbers` | Every turn number in the session |
| `focus_turn` | The turn centred on |
| `has_earlier`, `has_later` | Whether there are turns outside the window |
| `turns` | `[{turn, at, prompts, summaries, notes, notes_total}]`. `prompts` items carry `agent: true` for subagent messages. `notes` (observations) is capped at 300 per turn, with `notes_total` giving the full count. Records carry `id`, `created_at_epoch` and the same fields as `detail` above. |

Returns 404 if the session is unknown or all its records are hidden.

## `GET /api/projects`

```json
{"projects": [{"project": "invoice-api", "n": 12, "last": 1783584000000}, …]}
```

Every project with visible records: its name, its record count, and its latest record's time. Most
recently active first.

## `GET /api/search`: the original search (legacy)

The first version's date-ordered search, kept for comparison in the benchmark. The page doesn't use it.
It reads claude-mem's own full-text tables, requires every word (prefix-matched), and searches one kind
at a time.

| Parameter | |
|---|---|
| `kind` | `observations` (default), `summaries` or `prompts` |
| `q`, `project`, `type`, `size` | As above |
| `page` | Default `-1`, the last page. Results run oldest to newest, so the last page holds the newest. |

Returns `kind`, `total`, `page`, `pages`, `size`, `first_index`, `terms` and `items` (raw rows).
