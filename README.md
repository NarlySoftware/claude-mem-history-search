# claude-mem history search

A local web page for finding things in your [claude-mem](https://github.com/thedotmack/claude-mem)
history, across all projects: observations, session summaries and your own prompts. Ask it the way you'd
ask a person ("where did we decide on the retry limit?") and it ranks what you've recorded.

- **Ranked keyword search.** Filler words are dropped, words are stemmed ("samples" finds "sampling"),
  and titles count more. Use `"exact phrase"` for a phrase and `-word` to leave a word out.
- **Typo tolerance.** "recieve" also tries "receive", using words that already appear in your history.
- **Meaning search.** It also asks claude-mem's own worker for meaning-based results (its Chroma
  vectors) and merges them in. If the worker isn't running, the page says so and searches keywords only.
- **Modes.** Conversation (your prompts and the session summaries), Notes (observations and summaries)
  and Everything. Filter by project and type, and sort by best match, newest or oldest.
- **Session view.** Opens a result's whole session, turn by turn, around the match.
  **Group by session** shows one card per session.
- **Phone-friendly**, with light, dark and auto themes. Plain HTML, CSS and JS, no build step.
- **Read-only.** It opens `claude-mem.db` read-only and never writes to it. It keeps its own search
  index in `data/index.db`, which is safe to delete and is rebuilt in a few seconds.

## Requirements

- claude-mem, installed and recording. Tested with 13.40; the server says if your database is
  missing anything it needs.
- Python 3.9 or newer with SQLite FTS5. macOS's own `/usr/bin/python3` works. Standard library only:
  nothing to `pip install`.
- macOS for the start-at-login installer. On Linux the server should run as is, but this is untested
  (see below).

## Quick start

```sh
git clone https://github.com/NarlySoftware/claude-mem-history-search.git
cd claude-mem-history-search
python3 -I server.py            # then open http://localhost:37690
```

The first start builds the index, which takes a few seconds per 50,000 records. After that, it picks
up new records every 10 seconds.

Options: `--port N` (default 37690), `--db PATH` (another `claude-mem.db`), and `--allow-user LOGIN`
(see "Other devices").

## Start at login (macOS)

```sh
./install.sh                    # options: --port N, --label NAME, --python PATH
./uninstall.sh
```

`install.sh` writes a LaunchAgent to `~/Library/LaunchAgents/local.claude-mem-history-search.plist`
and starts it. launchd then starts it at every login and restarts it if it stops. The log is
`~/Library/Logs/claude-mem-history-search.log`. To restart it after changing the code:
`launchctl kickstart -k gui/$(id -u)/local.claude-mem-history-search`. Run `install.sh` again if you
move the folder.

If the folder is in `~/Documents` or `~/Desktop`, the first start can take about 20 seconds while
macOS checks Python's access to it.

**Linux (untested):** run `python3 -I server.py` however you like to run services, for example from a
systemd user unit (`~/.config/systemd/user/claude-mem-history-search.service` with `ExecStart=/usr/bin/python3 -I
/path/to/server.py` and `Restart=always`).

## How it finds claude-mem

The same way claude-mem 13.40 does, so a standard install needs no setup:

- **Data folder:** `CLAUDE_MEM_DATA_DIR` from the environment, else from `~/.claude-mem/settings.json`,
  else `~/.claude-mem`. The database is `claude-mem.db` inside it.
- **Worker** (for meaning search): `CLAUDE_MEM_WORKER_HOST` and `CLAUDE_MEM_WORKER_PORT` from the
  environment, else from `<data folder>/settings.json`, else `127.0.0.1` and port 37700 plus your
  user id mod 100.

## Other devices (optional, Tailscale)

The server only listens on `127.0.0.1`. To use the page from your phone or another computer, you can
publish it to your own tailnet with [Tailscale](https://tailscale.com) Serve. This is not Funnel, so it
isn't reachable from the internet:

```sh
tailscale serve --bg --https=8443 http://127.0.0.1:37690
```

Then open `https://<this-machine>.<tailnet>.ts.net:8443/`. The server only answers requests that come
in through Tailscale from your own Tailscale login (read at start-up), plus any `--allow-user LOGIN`.
Tagged machines and machines shared in from other tailnets get 403. Without Tailscale it simply stays
local.

**Your claude-mem database holds your full conversation history.** Don't bind the server to
`0.0.0.0` or put it behind a public proxy or Funnel.

## Hiding records

Work on this tool gets recorded by claude-mem too, and those records would crowd your results, so this
project's own records are always hidden. To hide more, copy `local.example.json` to `local.json`:

- `"hide_projects": ["name", …]` hides whole projects.
- `"hide_marked": [{"project": "name", "markers": ["word", …]}]` hides only the records in that project
  that mention one of the words.

Changing these rebuilds the index on the next start.

## API

Everything the page does goes through a small JSON API, which you can use too:

- `GET /api/find?q=&mode=conversation|notes|everything&project=&type=&sort=best|newest|oldest&page=&size=&meaning=1|0&group=1`
- `GET /api/session?session=&turn=&before=2&after=2`
- `GET /api/projects`

## Tests and benchmark

```sh
python3 -I tests/test_search.py
python3 -I tests/test_api.py
HISTORY_SEARCH_TESTS=live python3 -I tests/test_search.py   # against your real database (read-only)
```

By default the tests build a small made-up `claude-mem.db` in a temporary folder, so they don't depend
on your history. `tests/phone.mjs` checks the page in an iPhone-sized WebKit, using Playwright (setup
steps are at the top of the file).

`bench/run.py` scores search quality (hit@1, hit@10, MRR) against queries you write about your own
records. The format is at the top of the file.

## License

MIT. See [LICENSE](LICENSE).
