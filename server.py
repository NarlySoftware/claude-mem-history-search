#!/usr/bin/env python3
"""Read-only history search for claude-mem.

Serves index.html and a small JSON API on 127.0.0.1 (port 37690 by default), reading
claude-mem's claude-mem.db in read-only mode (never writes, safe with the worker running;
config.py finds it the way claude-mem does). Exact totals make First/Last paging possible, which the
worker's own API can't do. /api/find is the ranked search the page uses (search.py, over our own
index in data/index.db); /api/search is the original date-ordered search, kept for comparison.

    python3 -I server.py [--port 37690] [--db PATH] [--allow-user LOGIN]
"""
import argparse, errno, json, os, re, sqlite3, subprocess, sys, threading, time
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # -I leaves this folder off the import path
import config, indexer, search as ranked_search  # noqa: E402

DB = indexer.DB
HERE = os.path.dirname(os.path.abspath(__file__))
MAIN_TYPES = ["discovery", "change", "feature", "bugfix", "decision", "refactor"]
MAX_SIZE = 100


def connect():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only = 1")
    return con


def terms(q):
    return re.findall(r"[\w][\w.\-]*", q or "")[:12]


def fts_query(q):
    # Quote each term so FTS syntax in user input can't break the query; prefix-match each.
    return " ".join('"%s"*' % t.replace('"', "") for t in terms(q))


def project_clause(alias, project, params):
    # This tool's own project is hidden here too, as in /api/find (search.HIDDEN_PROJECTS).
    params += list(ranked_search.HIDDEN_PROJECTS)
    clause = f" AND COALESCE({alias}.project, '') NOT IN ({','.join('?' * len(ranked_search.HIDDEN_PROJECTS))})"
    if not project:
        return clause
    params += [project, project]
    return clause + f" AND ({alias}.project = ? OR {alias}.merged_into_project = ?)"


def build(kind, q, project, otype):
    """Return (from_where_sql, params, select_cols, order_col)."""
    params = []
    if kind == "observations":
        sql = " FROM observations o"
        where = " WHERE 1=1"
        if terms(q):
            sql += " JOIN observations_fts f ON f.rowid = o.id"
            where += " AND observations_fts MATCH ?"
            params.append(fts_query(q))
        where += project_clause("o", project, params)
        if otype == "other":
            where += " AND o.type NOT IN (%s)" % ",".join("?" * len(MAIN_TYPES))
            params += MAIN_TYPES
        elif otype:
            where += " AND o.type = ?"
            params.append(otype)
        cols = ("o.id, o.project, o.type, o.title, o.subtitle, o.narrative, o.facts, "
                "o.files_read, o.files_modified, o.created_at_epoch, "
                "(SELECT ss.platform_source FROM sdk_sessions ss "
                "WHERE ss.memory_session_id = o.memory_session_id) AS platform_source")
        return sql + where, params, cols, "o"
    if kind == "summaries":
        sql = " FROM session_summaries s"
        where = " WHERE 1=1"
        if terms(q):
            sql += " JOIN session_summaries_fts f ON f.rowid = s.id"
            where += " AND session_summaries_fts MATCH ?"
            params.append(fts_query(q))
        where += project_clause("s", project, params)
        cols = ("s.id, s.project, s.request, s.investigated, s.learned, s.completed, "
                "s.next_steps, s.notes, s.files_read, s.files_edited, s.created_at_epoch")
        return sql + where, params, cols, "s"
    # prompts: no FTS table, so AND of LIKE terms; project comes from the session
    sql = " FROM user_prompts p LEFT JOIN sdk_sessions ss ON ss.content_session_id = p.content_session_id"
    where = " WHERE 1=1"
    for t in terms(q):
        where += " AND p.prompt_text LIKE ? ESCAPE '\\'"
        params.append("%" + t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    where += f" AND COALESCE(ss.project, '') NOT IN ({','.join('?' * len(ranked_search.HIDDEN_PROJECTS))})"
    params += list(ranked_search.HIDDEN_PROJECTS)
    if project:
        where += " AND ss.project = ?"
        params.append(project)
    cols = ("p.id, ss.project AS project, ss.platform_source AS platform_source, "
            "p.prompt_number, p.prompt_text, p.created_at_epoch")
    return sql + where, params, cols, "p"


def search(qs):
    kind = qs.get("kind", "observations")
    if kind not in ("observations", "summaries", "prompts"):
        kind = "observations"
    q = qs.get("q", "").strip()
    project = qs.get("project", "")
    otype = qs.get("type", "") if kind == "observations" else ""
    size = max(5, min(MAX_SIZE, int(qs.get("size", 25) or 25)))
    page = int(qs.get("page", -1) or -1)  # -1 = last page (newest)

    body, params, cols, a = build(kind, q, project, otype)
    with closing(connect()) as con:
        total = con.execute("SELECT COUNT(*)" + body, params).fetchone()[0]
        pages = max(1, -(-total // size))
        page = pages if page == -1 or page > pages else max(1, page)
        rows = con.execute(
            f"SELECT {cols}{body} ORDER BY {a}.created_at_epoch, {a}.id LIMIT ? OFFSET ?",
            params + [size, (page - 1) * size],
        ).fetchall()
    return {"kind": kind, "total": total, "page": page, "pages": pages, "size": size,
            "first_index": (page - 1) * size + 1 if total else 0,
            "terms": terms(q), "items": [dict(r) for r in rows]}


def find(qs):
    return ranked_search.find(
        q=qs.get("q", "").strip(), mode=qs.get("mode", "everything"), project=qs.get("project", ""),
        otype=qs.get("type", ""), sort=qs.get("sort", ""), page=int(qs.get("page", 1) or 1),
        size=max(5, min(MAX_SIZE, int(qs.get("size", 25) or 25))), use_semantic=qs.get("meaning", "1") != "0",
        group=qs.get("group") == "1")


def projects():
    return {"projects": ranked_search.projects()}


# Who may use the page through `tailscale serve` (requests arrive from 127.0.0.1 with a *.ts.net Host and
# Tailscale's identity headers). Filled at startup with this Mac's own Tailscale login, plus --allow-user.
TAILNET_USERS = set()
LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}


def tailscale_login():
    """The Tailscale login this Mac is signed in as, or None."""
    for exe in ("tailscale", "/usr/local/bin/tailscale", "/Applications/Tailscale.app/Contents/MacOS/Tailscale"):
        try:
            out = subprocess.run([exe, "status", "--json"], capture_output=True, timeout=5, check=True).stdout
            d = json.loads(out)
            return d["User"][str(d["Self"]["UserID"])]["LoginName"]
        except (OSError, subprocess.SubprocessError, ValueError, KeyError):
            continue
    return None


def allowed(headers):
    """Local requests by name only (a page on some other host name pointed at 127.0.0.1 — DNS
    rebinding — is refused). Through Tailscale, only listed users; shared-in or tagged machines
    carry no matching login."""
    host = (headers.get("Host") or "").lower()
    name = host.rsplit(":", 1)[0] if not host.endswith("]") else host
    if name in LOCAL_HOSTS:
        return True
    if name.endswith(".ts.net"):
        return (headers.get("Tailscale-User-Login") or "").lower() in TAILNET_USERS
    return False


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not allowed(self.headers):
            print(f"refused {self.path[:80]!r}: Host={self.headers.get('Host')!r} "
                  f"Tailscale-User-Login={self.headers.get('Tailscale-User-Login')!r}", flush=True)
            return self.send(403, "forbidden", "text/plain")
        u = urlparse(self.path)
        qs = {k: v[-1] for k, v in parse_qs(u.query).items()}
        try:
            if u.path in ("/", "/index.html"):
                with open(os.path.join(HERE, "index.html"), "rb") as f:
                    return self.send(200, f.read(), "text/html; charset=utf-8")
            if u.path == "/api/projects":
                return self.send(200, json.dumps(projects()), "application/json")
            if u.path == "/api/find":
                return self.send(200, json.dumps(find(qs)), "application/json")
            if u.path == "/api/session":
                view = ranked_search.session_view(
                    qs.get("session", ""), turn=int(qs["turn"]) if qs.get("turn") else None,
                    before=min(200, int(qs.get("before", 2) or 0)), after=min(200, int(qs.get("after", 2) or 0)))
                if view is None:
                    return self.send(404, json.dumps({"error": "session not found"}), "application/json")
                return self.send(200, json.dumps(view), "application/json")
            if u.path == "/api/search":
                return self.send(200, json.dumps(search(qs)), "application/json")
            self.send(404, "not found", "text/plain")
        except (sqlite3.Error, ValueError) as e:
            self.send(400, json.dumps({"error": str(e)}), "application/json")


def keep_index_fresh(every=10):
    """Top up our search index (data/index.db) from claude-mem.db in the background."""
    while True:
        time.sleep(every)
        try:
            added, rebuilt, secs = indexer.sync()
            if rebuilt:  # appends happen every few seconds while claude-mem is busy; not worth a log line
                print(f"index rebuilt: {added} records in {secs}s", flush=True)
        except sqlite3.Error as e:
            print(f"index sync failed: {e}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=config.DEFAULT_PORT)
    ap.add_argument("--db", help="claude-mem.db to read (default: found the way claude-mem finds it)")
    ap.add_argument("--allow-user", action="append", default=[],
                    help="Tailscale login allowed through `tailscale serve` (this Mac's own login is always allowed)")
    args = ap.parse_args()
    port = args.port
    if args.db:
        DB = indexer.DB = os.path.abspath(os.path.expanduser(args.db))
    for problem in indexer.check_source():
        sys.exit(problem)
    if port == config.worker_port():
        sys.exit(f"port {port} is the claude-mem worker's; choose another with --port")
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as e:
        if e.errno != errno.EADDRINUSE:
            raise
        sys.exit(f"port {port} is already in use (another copy running?); choose another with --port")
    TAILNET_USERS.update(u.lower() for u in args.allow_user + [tailscale_login() or ""] if u)
    print(f"tailnet users allowed: {', '.join(sorted(TAILNET_USERS)) or 'none'}", flush=True)
    added, rebuilt, secs = indexer.sync()
    print(f"index ready: +{added} ({'rebuilt' if rebuilt else 'incremental'}, {secs}s)", flush=True)
    threading.Thread(target=keep_index_fresh, daemon=True).start()
    print(f"claude-mem history search: http://localhost:{port}", flush=True)
    httpd.serve_forever()
