"""Score search engines against the known-item benchmark.

    python3 -I bench/run.py [--engine baseline] [--show-misses] [--save]

Each query has one target record. An engine returns a ranked list of (kind, id) for a query;
we look for the target (strict) and for any record from the target's session (session).
Metrics: hit@1, hit@10, MRR (reciprocal rank, over the top 50). Higher is better.

The queries are your own: they name records in your claude-mem.db, so none ship with the code. Write
bench/queries.json (and optionally user_queries.json, the same shape, for queries written blind) as
    {"queries": [{"id": "q1", "style": "exact" | "concept" | "user", "query": "why did the login break",
                  "target": {"kind": "observation" | "summary" | "prompt", "id": 1234}}]}
"""
import argparse, json, os, sqlite3, sys, time
from contextlib import closing

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import server  # noqa: E402
import search  # noqa: E402

DEPTH = 50
# claude-mem records the sessions that build this tool, including talk about benchmark queries,
# so those records would leak answers into the results. Engines leave this project out.
EXCLUDE = ("claude-mem-history-search",)
MODE = "everything"  # --mode
SERVER_KIND = {"observation": "observations", "summary": "summaries", "prompt": "prompts"}


def baseline(query, kind_hint):
    """Today's tool, as the UI shows it: newest first. It needs the record kind chosen up front,
    so it gets the target's kind for free; a unified engine won't get that hint."""
    body, params, _, a = server.build(SERVER_KIND[kind_hint], query, "", "")
    body += f" AND COALESCE({a}.project, '') != ?" if a != "p" else " AND COALESCE(ss.project, '') != ?"
    params = params + [EXCLUDE[0]]
    with closing(server.connect()) as con:
        rows = con.execute(f"SELECT {a}.id{body} ORDER BY {a}.created_at_epoch DESC, {a}.id DESC LIMIT ?",
                           params + [DEPTH]).fetchall()
    return [(kind_hint, r[0]) for r in rows]


def ranked(query, kind_hint):
    """What the page runs: search.find in Everything mode, best match, all kinds at once (no kind hint)."""
    r = search.find(query, mode=MODE, size=DEPTH, hidden=EXCLUDE, details=False, use_semantic=False)
    return [(it["kind"], it["src_id"]) for it in r["items"]]


def hybrid(query, kind_hint):
    """ranked + the worker's meaning-based results, fused by reciprocal rank (Phase 3)."""
    r = search.find(query, mode=MODE, size=DEPTH, hidden=EXCLUDE, details=False)
    if r["semantic"] is False:
        sys.exit("worker unavailable: hybrid scores would be keyword-only")
    return [(it["kind"], it["src_id"]) for it in r["items"]]


def semantic_only(query, kind_hint):
    """The worker's results alone, fused across kinds, for comparison."""
    saved = search.KEYWORD_WEIGHT
    search.KEYWORD_WEIGHT = 0.0
    try:
        return hybrid(query, kind_hint)
    finally:
        search.KEYWORD_WEIGHT = saved


def grouped(query, kind_hint):
    """hybrid with results grouped by session: each session's best record, in session order. Only the
    session metrics mean anything here (rank = the session's place in the grouped list)."""
    r = search.find(query, mode=MODE, size=DEPTH, hidden=EXCLUDE, details=False, group=True)
    return [(g["items"][0]["kind"], g["items"][0]["src_id"]) for g in r["groups"] if g["items"]]


ENGINES = {"baseline": baseline, "ranked": ranked, "hybrid": hybrid, "semantic": semantic_only, "grouped": grouped}


def session_of(con, kind, rid):
    if kind == "observation":
        sql = "SELECT memory_session_id FROM observations WHERE id = ?"
    elif kind == "summary":
        sql = "SELECT memory_session_id FROM session_summaries WHERE id = ?"
    else:
        sql = ("SELECT ss.memory_session_id FROM user_prompts p JOIN sdk_sessions ss "
               "ON ss.content_session_id = p.content_session_id WHERE p.id = ?")
    row = con.execute(sql, (rid,)).fetchone()
    return row[0] if row else None


def load_queries():
    path = os.path.join(HERE, "queries.json")
    if not os.path.exists(path):
        sys.exit(f"no {path}: write your own queries first (format at the top of bench/run.py)")
    qs = json.load(open(path))["queries"]
    uq = os.path.join(HERE, "user_queries.json")
    if os.path.exists(uq):
        for q in json.load(open(uq))["queries"]:
            for key in ("query", "query2"):
                if q.get(key):
                    qs.append(dict(q, id=q["id"] + ("" if key == "query" else "-2"), query=q[key]))
    return qs


def score(engine, queries):
    sessions = {}
    out = []
    with closing(server.connect()) as con:
        for q in queries:
            t = q["target"]
            key = (t["kind"], t["id"])
            start = time.perf_counter()
            ranked = ENGINES[engine](q["query"], t["kind"])[:DEPTH]
            ms = (time.perf_counter() - start) * 1000
            if key not in sessions:
                sessions[key] = session_of(con, *key)
            for k in ranked:
                if k not in sessions:
                    sessions[k] = session_of(con, *k)
            strict = next((i + 1 for i, k in enumerate(ranked) if k == key), None)
            sess = next((i + 1 for i, k in enumerate(ranked) if sessions[k] and sessions[k] == sessions[key]), None)
            out.append(dict(id=q["id"], style=q["style"], kind=t["kind"], query=q["query"],
                            strict=strict, session=sess, returned=len(ranked), ms=round(ms, 1)))
    return out


def summarize(rows):
    def m(rs, field):
        n = len(rs) or 1
        ranks = [r[field] for r in rs]
        return (sum(1 for x in ranks if x == 1) / n, sum(1 for x in ranks if x and x <= 10) / n,
                sum(1 / x for x in ranks if x) / n)
    groups = [("all", rows)]
    for style in ("exact", "concept", "user"):
        groups.append((style, [r for r in rows if r["style"] == style]))
    for kind in ("summary", "observation", "prompt"):
        groups.append((kind, [r for r in rows if r["kind"] == kind]))
    table = []
    for name, rs in groups:
        if rs:
            s, e = m(rs, "strict"), m(rs, "session")
            table.append(dict(group=name, n=len(rs), strict_hit1=s[0], strict_hit10=s[1], strict_mrr=s[2],
                              session_hit1=e[0], session_hit10=e[1], session_mrr=e[2],
                              zero_results=sum(1 for r in rs if r["returned"] == 0) / len(rs)))
    return table


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="baseline", choices=sorted(ENGINES))
    ap.add_argument("--mode", default="everything", choices=sorted(search.MODES),
                    help="record kinds the ranked engine searches; a target outside them can still be found by session")
    ap.add_argument("--show-misses", action="store_true")
    ap.add_argument("--save", action="store_true", help="write bench/results/<engine>.json")
    args = ap.parse_args()
    global MODE
    MODE = args.mode
    rows = score(args.engine, load_queries())
    table = summarize(rows)
    print(f"engine: {args.engine}   mode: {MODE}   queries: {len(rows)}   median ms: "
          f"{sorted(r['ms'] for r in rows)[len(rows) // 2]}")
    print(f"{'group':<12}{'n':>4} | {'strict hit@1':>12}{'hit@10':>8}{'MRR':>6} | "
          f"{'session hit@1':>13}{'hit@10':>8}{'MRR':>6} | {'no results':>10}")
    for t in table:
        print(f"{t['group']:<12}{t['n']:>4} | {t['strict_hit1']:>12.0%}{t['strict_hit10']:>8.0%}"
              f"{t['strict_mrr']:>6.2f} | {t['session_hit1']:>13.0%}{t['session_hit10']:>8.0%}"
              f"{t['session_mrr']:>6.2f} | {t['zero_results']:>10.0%}")
    if args.show_misses:
        print("\nmisses (session rank > 10 or not found):")
        for r in rows:
            if not r["session"] or r["session"] > 10:
                print(f"  {r['id']:<10} {r['style']:<8} returned={r['returned']:<3} {r['query']}")
    if args.save:
        os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
        path = os.path.join(HERE, "results", f"{args.engine}.json")
        json.dump({"engine": args.engine, "when": time.strftime("%Y-%m-%d %H:%M"), "summary": table,
                   "rows": rows}, open(path, "w"), indent=1)
        print("saved", path)


if __name__ == "__main__":
    main()
