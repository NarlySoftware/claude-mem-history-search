"""Correctness tests for server.py, against a made-up claude-mem.db (see tests/env.py).

    python3 -I tests/test_api.py
    HISTORY_SEARCH_TESTS=live python3 -I tests/test_api.py    # against your real database (read-only)

They check behaviour, not exact counts, since the worker keeps adding records.
"""
import json, os, sqlite3, sys, threading, unittest
from contextlib import closing
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import env  # noqa: E402,F401  (must come before server)
import server  # noqa: E402

KINDS = ("observations", "summaries", "prompts")
NASTY = ['"', 'foo"*', "AND (", "NEAR(x y)", "a OR", "*", "-", "^x", "col:val", "%_\\", "'; DROP TABLE x;--",
         "日本語", "😀", "x" * 500, " ".join(["word"] * 40)]


def search(**qs):
    return server.search({k: str(v) for k, v in qs.items()})


class ReadOnly(unittest.TestCase):
    def test_connection_refuses_writes(self):
        with closing(server.connect()) as con:
            with self.assertRaises(sqlite3.Error):
                con.execute("CREATE TABLE _should_never_exist (x)")

    def test_query_only_pragma(self):
        with closing(server.connect()) as con:
            self.assertEqual(con.execute("PRAGMA query_only").fetchone()[0], 1)


class Paging(unittest.TestCase):
    def test_shape_and_totals(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                r = search(kind=kind, size=25, page=1)
                for key in ("total", "page", "pages", "size", "first_index", "terms", "items"):
                    self.assertIn(key, r)
                self.assertEqual(r["pages"], max(1, -(-r["total"] // 25)))
                self.assertEqual(len(r["items"]), min(25, r["total"]))

    def test_default_page_is_last(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                r = search(kind=kind, size=25)
                self.assertEqual(r["page"], r["pages"])
                self.assertEqual(len(r["items"]), r["total"] - (r["pages"] - 1) * 25)

    def test_out_of_range_pages_clamp(self):
        last = search(kind="summaries", size=25)
        self.assertEqual(search(kind="summaries", size=25, page=10**6)["page"], last["pages"])
        self.assertEqual(search(kind="summaries", size=25, page=0)["page"], 1)
        self.assertEqual(search(kind="summaries", size=25, page=-5)["page"], 1)

    def test_size_clamped(self):
        self.assertEqual(search(kind="observations", size=1, page=1)["size"], 5)
        self.assertEqual(search(kind="observations", size=10**6, page=1)["size"], server.MAX_SIZE)

    def test_chronological_and_no_overlap(self):
        a = search(kind="observations", q="sqlite", size=5, page=1)["items"]
        b = search(kind="observations", q="sqlite", size=5, page=2)["items"]
        self.assertTrue(b)
        keys = [(i["created_at_epoch"], i["id"]) for i in a + b]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(len(set(k[1] for k in keys)), len(keys))

    def test_first_index(self):
        r = search(kind="observations", size=10, page=3)
        self.assertEqual(r["first_index"], 21)
        self.assertEqual(search(kind="observations", q="zzqqxxnotaword", size=10)["first_index"], 0)


class Matching(unittest.TestCase):
    def test_nasty_input_never_errors(self):
        for kind in KINDS:
            for q in NASTY:
                with self.subTest(kind=kind, q=q[:20]):
                    r = search(kind=kind, q=q, size=5, page=1)
                    self.assertIsInstance(r["total"], int)

    def test_terms_are_anded(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                one = search(kind=kind, q="search", page=1)["total"]
                two = search(kind=kind, q="search database", page=1)["total"]
                self.assertLessEqual(two, one)

    def test_prompt_like_is_escaped(self):
        # '%' and '_' must be literal, not wildcards
        self.assertLessEqual(search(kind="prompts", q="_", page=1)["total"],
                             search(kind="prompts", page=1)["total"])
        r = search(kind="prompts", q="100%", size=100, page=1)
        for item in r["items"]:
            self.assertIn("100", item["prompt_text"])

    def test_prompt_matches_contain_terms(self):
        r = search(kind="prompts", q="database search", size=100, page=1)
        for item in r["items"]:
            text = item["prompt_text"].lower()
            self.assertIn("database", text)
            self.assertIn("search", text)


class Filters(unittest.TestCase):
    def setUp(self):
        self.projects = server.projects()["projects"]

    def test_projects_listed_newest_first(self):
        lasts = [p["last"] for p in self.projects]
        self.assertEqual(lasts, sorted(lasts, reverse=True))
        self.assertGreater(len(self.projects), 1)

    def test_project_filter(self):
        name = self.projects[0]["project"]
        for kind in KINDS:
            with self.subTest(kind=kind):
                r = search(kind=kind, project=name, size=50, page=1)
                if kind == "prompts":  # others may match via merged_into_project, which items don't carry
                    for item in r["items"]:
                        self.assertEqual(item["project"], name)
                self.assertLessEqual(r["total"], search(kind=kind, page=1)["total"])

    def test_type_filters_partition(self):
        total = search(kind="observations", page=1)["total"]
        parts = sum(search(kind="observations", type=t, page=1)["total"] for t in server.MAIN_TYPES + ["other"])
        self.assertEqual(parts, total)

    def test_unknown_kind_falls_back(self):
        self.assertEqual(search(kind="bogus", page=1)["kind"], "observations")


class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def get(self, path):
        with urlopen(self.base + path, timeout=10) as r:
            return r.status, r.headers, r.read()

    def test_index(self):
        status, headers, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"<html", body.lower())

    def test_api_json(self):
        for path in ("/api/projects", "/api/search?kind=summaries&q=sqlite", '/api/search?q=%22*%20AND%20(',
                     "/api/find?q=why+did+the+login+break", "/api/find?mode=conversation&sort=oldest&page=-1",
                     '/api/find?q=%22*%20AND%20(&mode=bogus&sort=bogus', "/api/find?q=login&group=1",
                     "/api/find?group=1&sort=oldest&page=-1"):
            with self.subTest(path=path):
                status, headers, body = self.get(path)
                self.assertEqual(status, 200)
                self.assertTrue(headers["Content-Type"].startswith("application/json"))
                json.loads(body)

    def test_session_endpoint(self):
        status, headers, body = self.get("/api/find?q=sqlite&size=5")
        item = json.loads(body)["items"][0]
        status, headers, body = self.get(f"/api/session?session={item['session']}&before=1&after=1")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["turns"])
        with self.assertRaises(HTTPError) as cm:
            self.get("/api/session?session=no-such-session")
        self.assertEqual(cm.exception.code, 404)

    def test_bad_number_is_400_not_crash(self):
        with self.assertRaises(HTTPError) as cm:
            self.get("/api/find?page=abc")
        self.assertEqual(cm.exception.code, 400)

    def test_404(self):
        with self.assertRaises(HTTPError) as cm:
            self.get("/nope")
        self.assertEqual(cm.exception.code, 404)

    def test_access_rules(self):
        server.TAILNET_USERS.add("owner@example.com")
        try:
            for host, login, ok in [("localhost:37690", None, True), ("127.0.0.1:37690", None, True),
                                    ("evil.example:37690", None, False),          # DNS rebinding
                                    ("me.tail1.ts.net:8443", "owner@example.com", True),
                                    ("me.tail1.ts.net:8443", "OWNER@example.com", True),
                                    ("me.tail1.ts.net:8443", "someone@else.com", False),
                                    ("me.tail1.ts.net:8443", None, False),          # tagged / shared-in node
                                    ("", None, False)]:
                with self.subTest(host=host, login=login):
                    h = {"Host": host} if host else {}
                    if login:
                        h["Tailscale-User-Login"] = login
                    self.assertEqual(server.allowed(h), ok)
        finally:
            server.TAILNET_USERS.discard("owner@example.com")

    def test_foreign_host_gets_403(self):
        req = Request(self.base + "/api/projects", headers={"Host": "evil.example"})
        with self.assertRaises(HTTPError) as cm:
            urlopen(req, timeout=10)
        self.assertEqual(cm.exception.code, 403)

    def test_no_path_traversal(self):
        with self.assertRaises(HTTPError):
            self.get("/../server.py")


if __name__ == "__main__":
    unittest.main(verbosity=1)
