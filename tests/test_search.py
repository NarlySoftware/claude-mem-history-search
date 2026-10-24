"""Tests for indexer.py (our index) and search.py (ranked search over it), against a made-up
claude-mem.db (see tests/env.py).

    python3 -I tests/test_search.py
    HISTORY_SEARCH_TESTS=live python3 -I tests/test_search.py    # against your real database and worker
"""
import json, os, sqlite3, sys, threading, unittest
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from env import LIVE  # noqa: E402  (must come before indexer)
import indexer, search  # noqa: E402
from test_api import NASTY  # noqa: E402


class Index(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        indexer.sync()

    def test_source_is_read_only(self):
        with closing(indexer.connect_source()) as con:
            with self.assertRaises(sqlite3.Error):
                con.execute("CREATE TABLE _should_never_exist (x)")

    def test_second_sync_is_incremental(self):
        added, rebuilt, _ = indexer.sync()
        self.assertFalse(rebuilt)

    def test_index_matches_source(self):
        indexer.sync()
        with closing(indexer.connect_source()) as src, closing(indexer.connect_index()) as idx:
            for kind, table in (("observation", "observations"), ("summary", "session_summaries"),
                                ("prompt", "user_prompts")):
                with self.subTest(kind=kind):
                    n_src = src.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    n_idx = idx.execute("SELECT COUNT(*) FROM docs WHERE kind = ?", (kind,)).fetchone()[0]
                    self.assertLessEqual(abs(n_src - n_idx), 5)  # the worker may write in between

    def test_needs_rebuild_on_deletion(self):
        with closing(indexer.connect_source()) as src:
            now = indexer.source_state(src)
            then = {t: list(v) for t, v in now.items()}
            self.assertFalse(indexer.needs_rebuild(src, then, now))
            then["observations"][0] += 1  # index thought there was one more row: something was deleted
            self.assertTrue(indexer.needs_rebuild(src, then, now))


class Query(unittest.TestCase):
    def test_filler_dropped(self):
        self.assertEqual(search.keywords("where did we talk about Maria's weekly sales report"),
                         ["maria", "weekly", "sales", "report"])

    def test_all_filler_keeps_words(self):
        self.assertEqual(search.keywords("where was it"), ["where", "was", "it"])

    def test_typo_suggestions(self):
        with closing(indexer.connect_index()) as con:
            self.assertIn("break", search.spellings(con, "beak"))
            self.assertEqual(search.spellings(con, "encoding"), [])  # common words are left alone
            self.assertIn("encod", search.spellings(con, "incoding"))
            self.assertNotIn("addit", search.spellings(con, "caddy"))  # a shifted word isn't a typo

    def test_parse(self):
        p = search.parse('where did we talk about "retry limit" backoff -redis')
        self.assertEqual(p, {"words": ["backoff"], "phrases": ["retry limit"], "excludes": ["redis"]})
        self.assertEqual(search.parse('"only a phrase"')["words"], [])
        self.assertEqual(search.parse('find "x y"')["words"], [])  # filler around a phrase is dropped

    def test_nasty_input_never_errors(self):
        for q in NASTY + ['"unclosed', '-', '--x', '""', '"" -', '-"x y"']:
            with self.subTest(q=q[:20]):
                self.assertIsInstance(search.find(q, size=5)["items"], list)

    def test_empty_query_browses_newest_first(self):
        r = search.find("", size=10)
        self.assertEqual(r["sort"], "newest")
        times = [it["created_at_epoch"] for it in r["items"]]
        self.assertEqual(times, sorted(times, reverse=True))
        self.assertFalse(r["capped"])

    def test_ranked_capped_and_paged(self):
        r1 = search.find("sqlite database", size=5, page=1, details=False)
        r2 = search.find("sqlite database", size=5, page=2, details=False)
        self.assertGreater(r1["pages"], 1)
        self.assertLessEqual(r1["total"], search.MAX_RANKED)
        ids = [it["rowid"] for it in r1["items"] + r2["items"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(r1["sort"], "best")

    def test_sort_by_date_keeps_same_matches(self):
        best = search.find("sqlite locked", size=100, details=False)
        newest = search.find("sqlite locked", sort="newest", size=100, details=False)
        self.assertEqual(best["total"], newest["total"])
        times = [it["created_at_epoch"] for it in newest["items"]]
        self.assertEqual(times, sorted(times, reverse=True))

    def test_modes_restrict_kinds(self):
        for mode, kinds in search.MODES.items():
            with self.subTest(mode=mode):
                r = search.find("search", mode=mode, size=100, details=False)
                self.assertTrue(r["items"])
                self.assertTrue(all(it["kind"] in kinds for it in r["items"]))

    def test_marked_records_hidden(self):
        if not indexer.HIDE_MARKED:
            self.skipTest("no hide_marked rule in local.json")
        for project, markers in indexer.HIDE_MARKED:
            with closing(indexer.connect_index()) as con:
                n, kept = con.execute("SELECT SUM(hidden), SUM(1 - hidden) FROM docs WHERE project = ?", (project,)).fetchone()
            self.assertGreater(n or 0, 0)
            self.assertGreater(kept, n)  # the rest of the project stays searchable
            r = search.find(" ".join(markers), size=100, details=False)
            with closing(indexer.connect_index()) as con:
                for it in r["items"]:
                    self.assertEqual(con.execute("SELECT hidden FROM docs WHERE rowid = ?", (it["rowid"],)).fetchone()[0], 0)
            self.assertTrue(search.find("", project=project, size=5, details=False)["items"])

    def test_hidden_project_never_shown(self):
        for q in ("", "search benchmark index"):
            r = search.find(q, size=100, details=False)
            self.assertNotIn(search.HIDDEN_PROJECTS[0], {it["project"] for it in r["items"]})
        self.assertNotIn(search.HIDDEN_PROJECTS[0], {p["project"] for p in search.projects()})

    def test_phrase_and_exclusion(self):
        phrase = search.find('"read only"', size=50, details=False)
        self.assertTrue(phrase["items"])
        with closing(indexer.connect_index()) as con:
            for it in phrase["items"]:
                title, body = con.execute("SELECT title, body FROM docs WHERE rowid = ?", (it["rowid"],)).fetchone()
                self.assertRegex(f"{title} {body}", r"(?i)\bread\W+only\b")
        with_x = search.find("sqlite", size=100, details=False)["total"]
        without = search.find("sqlite -wal", size=100, details=False)
        self.assertLessEqual(without["total"], with_x)
        with closing(indexer.connect_index()) as con:
            for it in without["items"]:
                title, body = con.execute("SELECT title, body FROM docs WHERE rowid = ?", (it["rowid"],)).fetchone()
                self.assertNotRegex(f"{title} {body}", r"(?i)\bwal\b")

    def test_conversation_leaves_out_agent_messages(self):
        conv = search.find("agent message report", mode="conversation", size=100, details=False)
        self.assertFalse([it for it in conv["items"] if it["kind"] == "prompt" and it["type"] == "agent"])
        every = search.find("agent message report", mode="everything", size=100, details=False)
        self.assertTrue([it for it in every["items"] if it["kind"] == "prompt" and it["type"] == "agent"])

    def test_semantic_fallback_when_worker_down(self):
        saved = search.WORKER
        search.WORKER = "http://127.0.0.1:9"  # nothing listens there
        try:
            r = search.find("zip reader library %d" % id(self), size=10, details=False)
        finally:
            search.WORKER = saved
        self.assertIs(r["semantic"], False)
        self.assertTrue(r["items"])

    def test_semantic_fused_and_filtered(self):
        """A stand-in worker returns a hidden record and one no keyword matches: the first is dropped,
        the second fused in."""
        with closing(indexer.connect_index()) as con:
            hidden = con.execute("SELECT src_id FROM docs WHERE kind = 'observation' AND hidden = 1").fetchone()[0]
            plain = con.execute("SELECT src_id FROM docs WHERE kind = 'observation' AND hidden = 0 "
                                "AND body NOT LIKE '%unzip%' AND title NOT LIKE '%unzip%'").fetchone()[0]

        class Worker(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                body = json.dumps({"observations": [{"id": hidden}, {"id": plain}], "sessions": [], "prompts": []})
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body.encode())

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Worker)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        saved = search.WORKER
        search.WORKER = "http://127.0.0.1:%d" % httpd.server_address[1]
        try:
            r = search.find("unzip code %d" % id(self), size=100, details=False)
        finally:
            search.WORKER = saved
            httpd.shutdown()
            httpd.server_close()
        self.assertIs(r["semantic"], True)
        ids = [it["src_id"] for it in r["items"] if it["kind"] == "observation"]
        self.assertIn(plain, ids)
        self.assertNotIn(hidden, ids)

    def test_semantic_used_and_filtered(self):
        if not LIVE:
            self.skipTest("needs the real worker (HISTORY_SEARCH_TESTS=live)")
        r = search.find("we wrote our own unzip code instead of using a library", mode="conversation",
                        size=100, details=False)
        if r["semantic"] is False:
            self.skipTest("claude-mem worker not running")
        self.assertIs(r["semantic"], True)
        self.assertTrue(all(it["kind"] in search.MODES["conversation"] for it in r["items"]))
        self.assertNotIn(search.HIDDEN_PROJECTS[0], {it["project"] for it in r["items"]})

    def test_semantic_skipped_for_exact_queries(self):
        self.assertIsNone(search.find('"read only"', size=5, details=False)["semantic"])
        self.assertIsNone(search.find("sqlite -wal", size=5, details=False)["semantic"])
        self.assertIsNone(search.find("sqlite", size=5, details=False, use_semantic=False)["semantic"])
        self.assertIsNone(search.find("", size=5, details=False)["semantic"])

    def test_session_view(self):
        with closing(indexer.connect_index()) as con:
            session, src_id = con.execute(
                "SELECT session, src_id FROM docs WHERE kind = 'observation' AND hidden = 0 AND session IN "
                "(SELECT session FROM docs GROUP BY session HAVING COUNT(*) BETWEEN 30 AND 300) LIMIT 1").fetchone()
        with closing(indexer.connect_source()) as src:
            turn = src.execute("SELECT prompt_number FROM observations WHERE id = ?", (src_id,)).fetchone()[0]
        v = search.session_view(session, turn=turn, before=1, after=1)
        self.assertEqual(v["focus_turn"], turn)
        shown = [t["turn"] for t in v["turns"]]
        self.assertIn(turn, shown)
        self.assertLessEqual(len(shown), 3)
        self.assertEqual(shown, sorted(shown))
        focus = next(t for t in v["turns"] if t["turn"] == turn)
        self.assertIn(src_id, [n["id"] for n in focus["notes"]])
        self.assertEqual(v["has_earlier"], shown[0] != v["turn_numbers"][0])
        everything = search.session_view(session, turn=turn, before=1000, after=1000)
        self.assertEqual([t["turn"] for t in everything["turns"]], everything["turn_numbers"])
        self.assertFalse(everything["has_earlier"] or everything["has_later"])

    def test_session_view_hides_and_rejects(self):
        self.assertIsNone(search.session_view("no-such-session"))
        with closing(indexer.connect_index()) as con:
            own = con.execute("SELECT session FROM docs WHERE project = ? LIMIT 1", (search.HIDDEN_PROJECTS[0],)).fetchone()
            mixed = con.execute("SELECT session, kind, src_id FROM docs WHERE hidden = 1 AND project NOT IN (%s) LIMIT 1"
                                % ",".join("?" * len(search.HIDDEN_PROJECTS)), search.HIDDEN_PROJECTS).fetchone()
        if own:
            self.assertIsNone(search.session_view(own[0]))
        if mixed:  # a session with some records about this tool (local.json hide_marked): those stay out
            v = search.session_view(mixed[0], before=1000, after=1000)
            kinds = {"prompts": "prompt", "summaries": "summary", "notes": "observation"}
            ids = {(kind, r["id"]) for t in v["turns"] for group, kind in kinds.items() for r in t[group]}
            self.assertNotIn((mixed[1], mixed[2]), ids)

    def test_group_by_session(self):
        flat = search.find("caddy login server", size=100, details=False, use_semantic=False)
        g = search.find("caddy login server", size=100, details=False, use_semantic=False, group=True)
        self.assertTrue(g["grouped"])
        sessions = [x["session"] for x in g["groups"]]
        self.assertEqual(len(sessions), len(set(sessions)))  # one card per session
        for x in g["groups"]:
            self.assertTrue(1 <= len(x["items"]) <= min(search.GROUP_SHOW, x["matches"]))
            self.assertTrue(all(it["session"] == x["session"] for it in x["items"]))
        # best order: sessions appear in the order of their first hit in the flat ranking
        first_seen = list(dict.fromkeys(it["session"] for it in flat["items"]))
        self.assertEqual(sessions[:5], first_seen[:5])
        self.assertNotIn(search.HIDDEN_PROJECTS[0], {x["project"] for x in g["groups"]})

    def test_group_browse_and_paging(self):
        r = search.find("", size=10, details=False, group=True)
        with closing(indexer.connect_index()) as con:
            n = con.execute("SELECT COUNT(DISTINCT COALESCE(session, '#' || rowid)) FROM docs d "
                            "WHERE hidden = 0 AND project NOT IN (%s)" % ",".join("?" * len(search.HIDDEN_PROJECTS)),
                            search.HIDDEN_PROJECTS).fetchone()[0]
        self.assertEqual(r["total"], n)
        lasts = [x["last_epoch"] for x in r["groups"]]
        self.assertEqual(lasts, sorted(lasts, reverse=True))  # newest-active sessions first
        last = search.find("", size=10, details=False, group=True, page=10**6)
        self.assertEqual(last["page"], last["pages"])
        self.assertTrue(last["groups"])
        self.assertEqual(search.find("sqlite", group=True, size=5, page=-1, details=False, use_semantic=False)["page"],
                         search.find("sqlite", group=True, size=5, details=False, use_semantic=False)["pages"])

    def test_type_filter_only_observations(self):
        r = search.find("", otype="bugfix", size=50, details=False)
        self.assertTrue(r["items"] and all(it["kind"] == "observation" and it["type"] == "bugfix" for it in r["items"]))

    def test_details_and_snippets(self):
        r = search.find("sqlite", size=10)
        for it in r["items"]:
            self.assertIn("detail", it)
            self.assertIn(search.HL_ON, (it["title_hl"] or "") + (it["snippet"] or ""))

    def test_project_filter(self):
        name = search.projects()[0]["project"]
        r = search.find("test", project=name, size=50, details=False)
        with closing(indexer.connect_index()) as con:
            for it in r["items"]:
                p, merged = con.execute("SELECT project, merged_into_project FROM docs WHERE rowid = ?",
                                        (it["rowid"],)).fetchone()
                self.assertIn(name, (p, merged))


if __name__ == "__main__":
    unittest.main(verbosity=1)
