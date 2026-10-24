"""Our own search index, built from claude-mem.db (which stays read-only).

One `docs` table holds every observation, session summary and user prompt as (title, body), with an
FTS5 index over it, `docs_stem` (porter stemming: "fixing" finds "fix"). Typos are handled at query
time from its vocabulary (search.py). It lives in data/index.db and is safe to delete; it is rebuilt.
A trigram index for partial words was tried and dropped: 257 MB and no benchmark gain.

    python3 -I indexer.py [--rebuild]      # bring the index up to date (full rebuild with --rebuild)
"""
import argparse, json, os, sqlite3, sys, time
from contextlib import closing

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # -I leaves this folder off the import path
import config  # noqa: E402

DB = config.db_path()
INDEX = config.index_path()
KINDS = ("observation", "summary", "prompt")
SCHEMA_VERSION = 2  # bump when the docs table changes; the index is then rebuilt from scratch

# Records about this tool itself are kept out of search (`hidden`), since claude-mem records the
# sessions that work on it and they crowd results. local.json can hide more: whole projects
# ("hide_projects") or, within a project, only records mentioning some words ("hide_marked":
# [{"project": ..., "markers": [...]}], e.g. work on this tool done from another project's folder).
LOCAL = config.local()
HIDDEN_PROJECTS = tuple(dict.fromkeys(["claude-mem-history-search", os.path.basename(config.HERE)]
                                      + [str(p) for p in LOCAL.get("hide_projects", [])]))
HIDE_MARKED = [(str(r["project"]), tuple(str(m).lower() for m in r.get("markers", [])))
               for r in LOCAL.get("hide_marked", []) if isinstance(r, dict) and r.get("project")]
HIDE_RULE = json.dumps([HIDDEN_PROJECTS, HIDE_MARKED])  # stored in the index; a change rebuilds it

# What we read from claude-mem.db; checked at start-up (claude-mem 13.40 has all of it).
REQUIRED = {"observations": ("memory_session_id", "project", "merged_into_project", "type", "title", "subtitle",
                             "narrative", "facts", "concepts", "text", "prompt_number", "created_at_epoch"),
            "session_summaries": ("memory_session_id", "project", "merged_into_project", "request",
                                  "investigated", "learned", "completed", "next_steps", "notes", "prompt_number"),
            "user_prompts": ("content_session_id", "prompt_number", "prompt_text", "created_at_epoch"),
            "sdk_sessions": ("content_session_id", "memory_session_id", "project", "platform_source")}

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
  rowid INTEGER PRIMARY KEY,
  kind TEXT NOT NULL, src_id INTEGER NOT NULL,
  project TEXT, merged_into_project TEXT, session TEXT, platform_source TEXT,
  type TEXT, created_at_epoch INTEGER,
  title TEXT, body TEXT, hidden INTEGER NOT NULL DEFAULT 0,
  UNIQUE (kind, src_id)
);
CREATE INDEX IF NOT EXISTS docs_time ON docs (created_at_epoch);
CREATE INDEX IF NOT EXISTS docs_session ON docs (session);
CREATE VIRTUAL TABLE IF NOT EXISTS docs_stem USING fts5(title, body, content='docs', content_rowid='rowid',
  tokenize='porter unicode61 remove_diacritics 2');
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v);
"""

# Each source query yields: src_id, project, merged_into_project, session, platform_source, type,
# created_at_epoch, title, body. Bodies join the text fields people would search.
SOURCES = {
    "observation": """
        SELECT o.id, o.project, o.merged_into_project, o.memory_session_id,
               (SELECT ss.platform_source FROM sdk_sessions ss WHERE ss.memory_session_id = o.memory_session_id),
               o.type, o.created_at_epoch, o.title,
               json_array(o.subtitle, o.narrative, o.facts, o.concepts, o.text)
        FROM observations o WHERE o.id > ? ORDER BY o.id""",
    "summary": """
        SELECT s.id, s.project, s.merged_into_project, s.memory_session_id,
               (SELECT ss.platform_source FROM sdk_sessions ss WHERE ss.memory_session_id = s.memory_session_id),
               NULL, s.created_at_epoch, s.request,
               concat_ws(char(10), s.investigated, s.learned, s.completed, s.next_steps, s.notes)
        FROM session_summaries s WHERE s.id > ? ORDER BY s.id""",
    "prompt": """
        SELECT p.id, ss.project, NULL, ss.memory_session_id, ss.platform_source,
               -- subagent hand-backs are recorded as prompts too; they aren't the user's words
               CASE WHEN ltrim(p.prompt_text) LIKE '<agent-message%' THEN 'agent' END,
               p.created_at_epoch, NULL, p.prompt_text
        FROM user_prompts p LEFT JOIN sdk_sessions ss ON ss.content_session_id = p.content_session_id
        WHERE p.id > ? ORDER BY p.id""",
}


def body_text(fields_json):
    """Observation fields as plain lines. facts and concepts are stored as JSON lists; flatten them so
    snippets read as text rather than ["…","…"]."""
    out = []
    for f in json.loads(fields_json):
        if not f:
            continue
        try:
            v = json.loads(f) if f.lstrip()[:1] == "[" else None
        except ValueError:
            v = None
        out += [str(x) for x in v if x] if isinstance(v, list) else [f]
    return "\n".join(out)


def connect_source():
    """claude-mem's own database, read-only. Never write to it."""
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)
    con.execute("PRAGMA query_only = 1")
    return con


def check_source():
    """Problems that stop us reading claude-mem.db, as a list of messages (empty if all is well)."""
    if not os.path.exists(DB):
        return [f"claude-mem database not found at {DB} (is claude-mem installed? set CLAUDE_MEM_DATA_DIR or --db)"]
    with closing(connect_source()) as src:
        missing = []
        for table, cols in REQUIRED.items():
            have = {r[1] for r in src.execute(f"PRAGMA table_info({table})")}
            missing += [f"{table}.{c}" for c in cols if c not in have] if have else [table]
    return [f"{DB} lacks {', '.join(missing)}: this needs a newer claude-mem (tested on 13.40)"] if missing else []


def is_hidden(project, title, body):
    if project in HIDDEN_PROJECTS:
        return True
    markers = [m for p, ms in HIDE_MARKED if p == project for m in ms]
    text = f"{title or ''}\n{body or ''}".lower() if markers else ""
    return any(m in text for m in markers)


def connect_index():
    os.makedirs(os.path.dirname(INDEX), exist_ok=True)
    con = sqlite3.connect(INDEX, timeout=10)
    con.execute("PRAGMA journal_mode = WAL")
    con.executescript(SCHEMA)
    version = con.execute("SELECT v FROM meta WHERE k = 'schema'").fetchone()
    if version is None or int(version[0]) != SCHEMA_VERSION:
        # An index from an older layout: start over (sync() then rebuilds it, ~2 s).
        con.executescript("DROP TABLE IF EXISTS docs_stem; DROP TABLE IF EXISTS docs; DELETE FROM meta;")
        con.executescript(SCHEMA)
        con.execute("INSERT INTO meta VALUES ('schema', ?)", (SCHEMA_VERSION,))
        con.commit()
    return con


TABLES = {"observations": True, "session_summaries": True, "user_prompts": False}  # has merged_into_project


def source_state(src):
    """Per source table: [row count, max id, rows with merged_into_project]."""
    return {t: list(src.execute(f"SELECT COUNT(*), COALESCE(MAX(id), 0), "
                                f"{'COUNT(merged_into_project)' if merged else '0'} FROM {t}").fetchone())
            for t, merged in TABLES.items()}


def needs_rebuild(src, then, now):
    """Appending new records only adds rows above the old max id. Anything else (deletions, project
    merges) can't be applied incrementally, so it triggers a rebuild."""
    for t in TABLES:
        if t not in then:
            return True
        n0, max0, merged0 = then[t]
        n1, _, merged1 = now[t]
        appended = src.execute(f"SELECT COUNT(*) FROM {t} WHERE id > ?", (max0,)).fetchone()[0]
        if n1 - n0 != appended or merged1 != merged0:
            return True
    return False


def sync(rebuild=False):
    """Append records newer than what the index holds; rebuild from scratch if the source changed
    in other ways. Returns (added, rebuilt, seconds)."""
    start = time.perf_counter()
    with closing(connect_source()) as src, closing(connect_index()) as idx:
        now = source_state(src)
        row = idx.execute("SELECT v FROM meta WHERE k = 'source_state'").fetchone()
        rule = idx.execute("SELECT v FROM meta WHERE k = 'hide_rule'").fetchone()
        if row is None or needs_rebuild(src, json.loads(row[0]), now) or rule is None or rule[0] != HIDE_RULE:
            rebuild = True
        if rebuild:
            idx.execute("DELETE FROM docs")
            idx.execute("INSERT INTO docs_stem(docs_stem) VALUES ('delete-all')")
        added = 0
        for kind in KINDS:
            last = idx.execute("SELECT COALESCE(MAX(src_id), 0) FROM docs WHERE kind = ?", (kind,)).fetchone()[0]
            rows = src.execute(SOURCES[kind], (last,)).fetchall()
            for r in rows:
                if kind == "observation":
                    r = (*r[:8], body_text(r[8]))
                cur = idx.execute(
                    "INSERT OR REPLACE INTO docs (kind, src_id, project, merged_into_project, session, "
                    "platform_source, type, created_at_epoch, title, body, hidden) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (kind, *tuple(r), int(is_hidden(r[1], r[7], r[8]) or r[2] in HIDDEN_PROJECTS)))
                rid = cur.lastrowid
                idx.execute("INSERT INTO docs_stem (rowid, title, body) VALUES (?,?,?)", (rid, r[7], r[8]))
            added += len(rows)
        idx.execute("INSERT OR REPLACE INTO meta VALUES ('source_state', ?)", (json.dumps(now),))
        idx.execute("INSERT OR REPLACE INTO meta VALUES ('hide_rule', ?)", (HIDE_RULE,))
        idx.execute("INSERT OR REPLACE INTO meta VALUES ('synced_at', ?)", (int(time.time()),))
        idx.commit()
    return added, rebuild, round(time.perf_counter() - start, 2)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true")
    rebuild = ap.parse_args().rebuild
    for problem in check_source():
        raise SystemExit(problem)
    added, rebuilt, secs = sync(rebuild)
    with closing(connect_index()) as idx:
        n = idx.execute("SELECT kind, COUNT(*) FROM docs GROUP BY kind").fetchall()
    print(f"added {added} ({'rebuilt' if rebuilt else 'incremental'}) in {secs}s; index now {dict(n)}; "
          f"{os.path.getsize(INDEX) / 1e6:.0f} MB")
