# Install

## Run it

```sh
git clone https://github.com/NarlySoftware/claude-mem-history-search.git
cd claude-mem-history-search
python3 -I server.py
```

Then open http://localhost:37690. Stop it with Ctrl-C.

`-I` (isolated mode) keeps Python from picking up modules from the current folder or your user
site-packages. The server works without it, but it's a good habit for anything that reads your data.

### Options

| Option | Default | |
|---|---|---|
| `--port N` | 37690 | Port to listen on (always `127.0.0.1`). It refuses claude-mem's worker port and says so if the port is taken. |
| `--db PATH` | found automatically | A different `claude-mem.db`, e.g. a copy or the demo database |
| `--allow-user LOGIN` | none | Another Tailscale login allowed in (repeatable); see [Other devices](#other-devices) |

### Environment variables

| Variable | |
|---|---|
| `CLAUDE_MEM_DATA_DIR`, `CLAUDE_MEM_WORKER_HOST`, `CLAUDE_MEM_WORKER_PORT` | claude-mem's own settings, read the same way claude-mem reads them (below) |
| `HISTORY_SEARCH_DB` | Same as `--db` |
| `HISTORY_SEARCH_INDEX` | Where to keep the search index (default `data/index.db` in this folder) |
| `HISTORY_SEARCH_LOCAL` | Local settings file (default `local.json` in this folder) |

## How it finds claude-mem

It works out the same locations claude-mem 13.40 does, so a standard install needs no setup:

1. **Data folder:** `CLAUDE_MEM_DATA_DIR` from the environment. If that's not set, `CLAUDE_MEM_DATA_DIR`
   in `~/.claude-mem/settings.json` (at the top level or inside an `"env"` object). Otherwise
   `~/.claude-mem`. The database is `claude-mem.db` in that folder.
2. **Worker** (used for meaning search): `CLAUDE_MEM_WORKER_HOST` and `CLAUDE_MEM_WORKER_PORT` from the
   environment. If they're not set, the same keys in `<data folder>/settings.json`. Otherwise
   `127.0.0.1` and port 37700 plus your user id mod 100 (37777 on systems without user ids).

If the database isn't found, the server stops with `claude-mem database not found at …`.

## Start at login (macOS)

```sh
./install.sh
```

This writes a LaunchAgent to `~/Library/LaunchAgents/local.claude-mem-history-search.plist` and starts
it. launchd then starts it at every login and restarts it 15 seconds after it stops. Before installing,
`install.sh` checks that Python is 3.9+ with FTS5 and that the claude-mem database can be read.

| Option | Default | |
|---|---|---|
| `--port N` | 37690 | Port the server listens on |
| `--label NAME` | `local.claude-mem-history-search` | LaunchAgent label (and plist file name) |
| `--python PATH` | `python3` on your PATH | Python to run it with |

Useful commands (use your label if you changed it):

```sh
launchctl kickstart -k gui/$(id -u)/local.claude-mem-history-search   # restart, e.g. after updating
launchctl bootout gui/$(id -u)/local.claude-mem-history-search         # stop until next login
tail -f ~/Library/Logs/claude-mem-history-search.log                   # the log
./uninstall.sh                                                         # stop and remove
```

Run `./install.sh` again after moving the folder or to change the port. It replaces the old agent.

If the folder is in `~/Documents`, `~/Desktop` or `~/Downloads`, macOS may take about 20 seconds over
the first start while it checks that Python may read the folder. It may also ask you to allow it.
Later starts take under a second.

## Linux (untested)

The server uses nothing macOS-specific apart from the optional Tailscale check, so it should run as is.
To start it with your session, a systemd user unit is the usual way:

```ini
# ~/.config/systemd/user/claude-mem-history-search.service
[Unit]
Description=claude-mem history search

[Service]
ExecStart=/usr/bin/python3 -I /path/to/claude-mem-history-search/server.py
Restart=always

[Install]
WantedBy=default.target
```

```sh
systemctl --user enable --now claude-mem-history-search
```

If you try it, an issue saying whether it worked would help.

## Other devices

The server only listens on `127.0.0.1`. To use the page from your phone or another computer, publish it
to your own tailnet with [Tailscale Serve](https://tailscale.com/kb/1312/serve). Serve keeps it private
to your tailnet. Don't use Funnel, which would put it on the internet.

```sh
tailscale serve --bg --https=8443 http://127.0.0.1:37690
```

Open `https://<this-machine>.<your-tailnet>.ts.net:8443/` on the other device. To turn it off:
`tailscale serve --https=8443 off`.

Through Tailscale, the server answers only:

- **your own Tailscale login.** It's read with `tailscale status --json` at start-up, so start or restart
  the server after Tailscale is signed in.
- **any login given with `--allow-user`.**

Anything else gets 403, including tagged machines and machines shared into your tailnet from someone
else's. The server prints refused requests to its log with the host and login, which helps when a
device can't get in. Without Tailscale installed, nothing changes: the page is just local.

## Hiding records

Sessions spent working on this tool get recorded by claude-mem too, and they would crowd your results.
So this project's own records (the project named `claude-mem-history-search`, or whatever this folder is
called) are always hidden. To hide more, copy `local.example.json` to `local.json`:

```json
{
  "hide_projects": ["some-project"],
  "hide_marked": [{"project": "another-project", "markers": ["word", "another phrase"]}]
}
```

- `hide_projects` hides whole projects.
- `hide_marked` hides only the records in a project that mention one of the markers (matched as plain
  text, ignoring case). It's for when a few sessions about something else were filed under another
  project.

Hidden records are left out of search, the project list and the session view. Changing `local.json`
rebuilds the index the next time the server starts.

## Updating

```sh
git pull
launchctl kickstart -k gui/$(id -u)/local.claude-mem-history-search   # or restart server.py by hand
```

If an update changes the index layout, the index is rebuilt automatically on start.

## Removing

```sh
./uninstall.sh            # if you installed the LaunchAgent
rm -rf claude-mem-history-search
```

That's everything: the index lives in the folder's `data/`, and nothing in claude-mem was changed.
