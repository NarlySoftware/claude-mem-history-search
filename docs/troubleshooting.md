# Troubleshooting

Start with the server's output: run `python3 -I server.py` in a terminal, or look at
`~/Library/Logs/claude-mem-history-search.log` if you installed the LaunchAgent.

### "claude-mem database not found at …"

claude-mem isn't installed, or its data is somewhere else. Check where claude-mem keeps it:
`CLAUDE_MEM_DATA_DIR` in your environment or in `~/.claude-mem/settings.json`. Or point the server
straight at the file with `--db /path/to/claude-mem.db`. See
[How it finds claude-mem](install.md#how-it-finds-claude-mem).

### "… lacks …: this needs a newer claude-mem"

The database is missing tables or columns this tool reads. That usually means an older claude-mem.
Update claude-mem, start it once so it upgrades its database, then try again. If you're on a *newer*
claude-mem and see this, please open an issue with the message.

### "port … is already in use"

Another copy is running. Perhaps the LaunchAgent and one you started by hand are both running, or
another program uses that port. Stop the other copy, or use `--port` with another number. With the
LaunchAgent installed, don't also start the server by hand on the same port.

### "port … is the claude-mem worker's"

You asked for the port claude-mem's worker uses. Pick another; the default, 37690, is outside
claude-mem's range.

### The page says "meaning search unavailable"

The claude-mem worker didn't answer within 3 seconds, so you're getting word matches only. Check that
claude-mem's worker is running. It normally starts with Claude Code; in a browser,
`http://127.0.0.1:<worker port>/api/health` should answer. If you run the worker on a non-default host or
port, set `CLAUDE_MEM_WORKER_HOST` / `CLAUDE_MEM_WORKER_PORT` where this tool can see them: in
claude-mem's `settings.json`, or in the environment of the server. Searches with a `"phrase"` or
`-exclusion` never use meaning search; that's by design.

### New conversations don't show up

The index is topped up every 10 seconds, but only with what claude-mem has written. claude-mem writes
observations and summaries as it processes each turn, which can lag behind the conversation, and
nothing at all while its worker is stopped.

### A record I expected is missing

- Check the mode: Conversation leaves out observations, Notes leaves out your prompts.
- Clear the project and type filters (the phone shows active filters under the search box).
- Is it in a hidden project? This tool's own project is always hidden, and `local.json` may hide more.
- Words must match by stem. Try the word's root, or turn Meaning on and describe it differently.
- Very broad queries keep only their best 500 matches. Narrow the query rather than paging.

### A phone or other device gets "forbidden"

- **Through Tailscale:** the server only lets in the Tailscale login it saw when it started. Restart it
  after signing in to Tailscale. Or, to let in someone else's login, start it with
  `--allow-user their@login`. The log shows each refused request with its host and login.
- **By IP address or another host name:** that's refused on purpose. Use `localhost` on the machine
  itself, and Tailscale Serve from elsewhere ([Other devices](install.md#other-devices)).

### The first start under launchd is slow, or macOS asks about folder access

If the folder is in `~/Documents`, `~/Desktop` or `~/Downloads`, macOS checks the first time that Python
may read it. This can take about 20 seconds or show a permission prompt. Allow it, or keep the folder
somewhere else, like `~/src`.

### `install.sh` says "Bootstrap failed: 5: Input/output error"

launchd hadn't finished removing the previous copy. `install.sh` waits up to 10 seconds for that. If
your machine is slow, run `./install.sh` again.

### The index seems wrong or out of date

Delete it and let it rebuild: stop the server, `rm -rf data/`, start the server. Or run
`python3 -I indexer.py --rebuild`. Rebuilding takes a few seconds and never touches claude-mem's data.

### Still stuck

Open an issue with:

- the server's output;
- your OS and Python version (`python3 --version`);
- your claude-mem version.

Leave out anything from your history.
