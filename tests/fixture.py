"""A small made-up claude-mem.db for the tests: the tables and columns we read (as in claude-mem 13.40),
with FTS tables kept up to date by the same triggers, and a few sessions of invented history.

    python3 -I tests/fixture.py OUT.db      # write one by hand, e.g. to try the page: server.py --db OUT.db
"""
import json, sqlite3, sys

SCHEMA = """
CREATE TABLE sdk_sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, content_session_id TEXT NOT NULL,
  memory_session_id TEXT UNIQUE, project TEXT NOT NULL, platform_source TEXT NOT NULL DEFAULT 'claude');
CREATE TABLE observations (id INTEGER PRIMARY KEY AUTOINCREMENT, memory_session_id TEXT NOT NULL,
  project TEXT NOT NULL, text TEXT, type TEXT NOT NULL, title TEXT, subtitle TEXT, facts TEXT, narrative TEXT,
  concepts TEXT, files_read TEXT, files_modified TEXT, prompt_number INTEGER, created_at TEXT NOT NULL,
  created_at_epoch INTEGER NOT NULL, merged_into_project TEXT);
CREATE TABLE session_summaries (id INTEGER PRIMARY KEY AUTOINCREMENT, memory_session_id TEXT NOT NULL,
  project TEXT NOT NULL, request TEXT, investigated TEXT, learned TEXT, completed TEXT, next_steps TEXT,
  files_read TEXT, files_edited TEXT, notes TEXT, prompt_number INTEGER, created_at TEXT NOT NULL,
  created_at_epoch INTEGER NOT NULL, merged_into_project TEXT);
CREATE TABLE user_prompts (id INTEGER PRIMARY KEY AUTOINCREMENT, content_session_id TEXT NOT NULL,
  prompt_number INTEGER NOT NULL, prompt_text TEXT NOT NULL, created_at TEXT NOT NULL,
  created_at_epoch INTEGER NOT NULL);
CREATE VIRTUAL TABLE observations_fts USING fts5(title, subtitle, narrative, text, facts, concepts,
  content='observations', content_rowid='id');
CREATE VIRTUAL TABLE session_summaries_fts USING fts5(request, investigated, learned, completed, next_steps,
  notes, content='session_summaries', content_rowid='id');
CREATE TRIGGER observations_ai AFTER INSERT ON observations BEGIN
  INSERT INTO observations_fts(rowid, title, subtitle, narrative, text, facts, concepts)
  VALUES (new.id, new.title, new.subtitle, new.narrative, new.text, new.facts, new.concepts);
END;
CREATE TRIGGER session_summaries_ai AFTER INSERT ON session_summaries BEGIN
  INSERT INTO session_summaries_fts(rowid, request, investigated, learned, completed, next_steps, notes)
  VALUES (new.id, new.request, new.investigated, new.learned, new.completed, new.next_steps, new.notes);
END;
"""

# Invented topics, cycled through the records. Chosen for the tests: typos ("beak" -> break,
# "incoding" -> encoding), phrases ("read only" vs "readings only"), exclusions (sqlite with and
# without WAL), LIKE escaping (100%), and a few words shared across sessions for grouping.
TOPICS = [
    "Why did the server login break after the caddy update",
    "The sqlite database was locked while the worker wrote in WAL mode",
    "Open the database read only so nothing is ever written",
    "We wrote our own unzip code instead of using a zip library",
    "Text encoding bug: files were saved with the wrong encoding",
    "Added a search box with paging and filters",
    "The readings only showed up after a restart",
    "Now 100% of the tests pass",
    "Use the api config path for the settings file",
    "The login server returned 502 behind caddy",
    "Addition of a new report page",
    "Sqlite full text search index with porter stemming",
]
TYPES = ["discovery", "change", "feature", "bugfix", "decision", "refactor", "○discovery"]

# (session, project, turns, observations per turn, merged_into_project). "maint" holds some records
# about this tool (hidden by the LOCAL rule below); the tool's own project is always hidden.
SESSIONS = [("s1", "alpha", 6, 5, None), ("s2", "beta", 2, 2, None), ("s3", "alpha", 2, 2, None),
            ("s4", "old-alpha", 2, 2, "alpha"), ("s5", "maint", 3, 2, None),
            ("s6", "claude-mem-history-search", 2, 2, None), ("s7", "beta", 2, 2, None)]
LOCAL = {"hide_marked": [{"project": "maint", "markers": ["history-search"]}]}
START = 1760000000


def build(path):
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    t, n = START, {"prompt": 0, "observation": 0, "summary": 0}  # each kind steps through all the topics
    for s, project, turns, per_turn, merged in SESSIONS:
        con.execute("INSERT INTO sdk_sessions (content_session_id, memory_session_id, project) VALUES (?,?,?)",
                    (f"content-{s}", f"mem-{s}", project))
        for turn in range(1, turns + 1):
            n["prompt"] += 1
            t += 60
            topic = TOPICS[n["prompt"] % len(TOPICS)]
            text = f"{topic}?" if s != "s5" or turn != 2 else "Check the history-search page on port 8443"
            con.execute("INSERT INTO user_prompts (content_session_id, prompt_number, prompt_text, created_at, "
                        "created_at_epoch) VALUES (?,?,?,?,?)", (f"content-{s}", turn, text, "", t))
            if s == "s1" and turn == 3:
                t += 1
                con.execute("INSERT INTO user_prompts (content_session_id, prompt_number, prompt_text, created_at, "
                            "created_at_epoch) VALUES (?,?,?,?,?)", (f"content-{s}", turn,
                            '<agent-message from="helper">agent message report: all done</agent-message>', "", t))
            for j in range(per_turn):
                n["observation"] += 1
                t += 30
                i = n["observation"]
                topic = TOPICS[i % len(TOPICS)]
                if s == "s5" and j == 0:
                    topic = "healthcheck for the worker" if turn != 2 else "history-search index rebuilt"
                con.execute(
                    "INSERT INTO observations (memory_session_id, project, text, type, title, subtitle, facts, "
                    "narrative, concepts, files_read, files_modified, prompt_number, created_at, created_at_epoch, "
                    "merged_into_project) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (f"mem-{s}", project, None, TYPES[i % len(TYPES)], topic, f"note {i}",
                     json.dumps([f"{topic}.", f"fact {i}"]), f"While working on {project}: {topic.lower()}.",
                     json.dumps(["how-it-works"]), "[]", "[]", turn, "", t, merged))
            n["summary"] += 1
            t += 30
            topic = TOPICS[(n["summary"] + 6) % len(TOPICS)]
            con.execute(
                "INSERT INTO session_summaries (memory_session_id, project, request, investigated, learned, "
                "completed, next_steps, files_read, files_edited, notes, prompt_number, created_at, "
                "created_at_epoch, merged_into_project) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"mem-{s}", project, topic, f"Looked into: {topic.lower()}", "Learned something", "Done",
                 "Nothing", "[]", "[]", None, turn, "", t, merged))
    con.commit()
    con.close()


if __name__ == "__main__":
    build(sys.argv[1])
