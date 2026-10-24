"""Ranked search over our own index (data/index.db, built by indexer.py).

Queries are written the way people ask ("where did we talk about X", "why did the login break"), so
filler and command words are dropped, terms are OR'd and ranked by bm25 with titles weighted up, and
uncommon words also try much commoner close spellings (likely typos). "exact phrase" must appear and
-word must not.

Meaning-based results come from the claude-mem worker's own search (Chroma vectors; address from config.py),
fused with ours by reciprocal rank. The worker's search is read-only (checked: no table changes). If it
is down or slow, results are keyword-only and `semantic` in the response says so.
"""
import difflib, json, re, time
from urllib.parse import urlencode
from urllib.request import urlopen
from contextlib import closing

import config, indexer

STOP = set("""
a about above after again all also am an and any are as at be because been before being below between
both but by can could did do does doing done down during each few for from further get got had has have
having he her here hers him his how i if in into is it its it's itself just let lets let's me more most my
no nor not now of off on once only or other our ours out over own same she should so some such than that
the their them then there these they this those through to too under until up very was we were what when
where which while who whom why will with would you your yours yourself
look lookup show find search tell check talk talked talking discuss discussed remember recall
thing things stuff something anything happen happened way ok okay please want need
""".split())

# Records about this tool itself are flagged `hidden` in the index (see indexer.is_hidden) and left out.
HIDDEN_PROJECTS = indexer.HIDDEN_PROJECTS
MODES = {"conversation": ("prompt", "summary"), "notes": ("observation", "summary"),
         "everything": ("observation", "summary", "prompt")}
MAIN_TYPES = ("discovery", "change", "feature", "bugfix", "decision", "refactor")
TITLE_WEIGHT = 3.0
MAX_RANKED = 500  # best matches kept for paging; OR queries match far more, mostly noise
WORKER = config.worker_url()
SEMANTIC_LIMIT = 50     # per record kind
SEMANTIC_TIMEOUT = 3.0  # seconds; the worker usually answers in ~0.5 s
RRF_K = 60              # reciprocal rank fusion: score = sum of weight / (RRF_K + rank)
# Semantic weight 0.25-0.75 all scored about the same (bench, 2026-10-23); 1.0 let the worker's
# results crowd out exact keyword hits on typo'd queries, since typo handling is ours alone.
KEYWORD_WEIGHT, SEMANTIC_WEIGHT = 1.0, 0.5
HL_ON, HL_OFF = "\x02", "\x03"  # highlight markers in titles/snippets; the page turns them into <mark>
_vocab, _vocab_at = None, 0.0
_semantic_cache = {}


def words(q):
    return [w.lower() for w in re.findall(r"[\w][\w.\-']*", q or "")][:24]


def keywords(q):
    ws = [w.strip(".-'") for w in words(q)]
    ws = [w[:-2] if w.endswith("'s") else w for w in ws]
    kept = [w for w in ws if w and w not in STOP]
    return kept or [w for w in ws if w]


def parse(q):
    """Split a query into free words (filler dropped), "quoted phrases" and -excluded words."""
    q = q or ""
    phrases = [" ".join(words(p)) for p in re.findall(r'"([^"]*)"', q)]
    rest = re.sub(r'"[^"]*"?', " ", q)
    excludes = [w.lower().strip(".-'") for w in re.findall(r"(?:^|\s)-([\w][\w.\-']*)", rest)]
    rest = re.sub(r"(?:^|\s)-[\w][\w.\-']*", " ", rest)
    free = keywords(rest)
    if phrases and all(w in STOP for w in words(rest)):
        free = []  # only filler around the phrase
    return {"words": free, "phrases": [p for p in phrases if p], "excludes": [x for x in excludes if x]}


def vocab(con, max_age=600):
    """term -> number of documents, from the stemmed index. Cached, reloaded every 10 minutes."""
    global _vocab, _vocab_at
    if _vocab is None or time.time() - _vocab_at > max_age:
        con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp.v USING fts5vocab(main, docs_stem, row)")
        _vocab, _vocab_at = dict(con.execute("SELECT term, doc FROM temp.v")), time.time()
    return _vocab


def stem_of(con, word):
    """How the porter tokenizer stores a word (e.g. 'samples' -> 'sampl')."""
    con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp.t USING fts5(x, tokenize='porter unicode61 remove_diacritics 2')")
    con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp.tv USING fts5vocab(temp, t, row)")
    con.execute("DELETE FROM temp.t")
    con.execute("INSERT INTO temp.t VALUES (?)", (word,))
    rows = [r[0] for r in con.execute("SELECT term FROM temp.tv")]
    return rows[0] if len(rows) == 1 else None


def spellings(con, word, uncommon=50, ratio=20):
    """Close spellings that are far more common than `word`, for likely typos. A typo can still turn up
    a few times in the history (or in talk about it), so this asks "is there a much commoner near
    neighbour?" rather than "is the word missing?". Suggestions are added to the word, never replace it."""
    if len(word) < 4 or not word.isalpha():
        return []
    v = vocab(con)
    target = stem_of(con, word) or word
    seen = v.get(target, 0)
    if seen >= uncommon:
        return []
    near = [t for t in v if len(t) >= 4 and abs(len(t) - len(target)) <= 2 and v[t] >= max(3, ratio * seen)]
    limit = 1 if len(target) <= 5 else 2  # letter edits allowed: a typo is a slip, not a different word
    scored = []
    for t in near:
        m = difflib.SequenceMatcher(None, target, t)
        if m.real_quick_ratio() >= 0.75 and m.quick_ratio() >= 0.75 and m.ratio() >= 0.75 \
                and edits(target, t, limit) <= limit:
            scored.append((round(m.ratio(), 2), v[t], t))  # equally close: prefer the commoner word
    return [t for _, _, t in sorted(scored, reverse=True)[:3]]


def edits(a, b, limit):
    """Levenshtein distance, stopping early once it exceeds `limit`."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > limit:
            return limit + 1
        prev = cur
    return prev[-1]


def quote(s):
    return '"%s"' % s.replace('"', "")


def match_expr(con, parsed):
    """FTS5 expression: (any free word, with typo alternatives) AND every phrase, NOT each exclusion.
    Returns (expression or None, stems to highlight)."""
    parts, terms = [], []
    if parsed["words"]:
        ors = []
        for w in parsed["words"]:
            alts = spellings(con, w)
            ors.append("(" + " OR ".join(quote(a) for a in [w] + alts) + ")" if alts else quote(w))
            terms += [stem_of(con, w) or w] + alts
        parts.append("(" + " OR ".join(ors) + ")")
    for p in parsed["phrases"]:
        parts.append(quote(p))
        terms += [stem_of(con, w) or w for w in p.split()]
    if not parts:
        return None, []
    expr = " AND ".join(parts)
    for x in parsed["excludes"]:
        expr = f"({expr}) NOT {quote(x)}"
    return expr, sorted(set(t for t in terms if t), key=len, reverse=True)


WORKER_KINDS = {"observations": "observation", "sessions": "summary", "prompts": "prompt"}


def semantic(text, project=""):
    """The worker's ranked ids per kind, {kind: [src_id, ...]}, or None if it can't be reached.
    Cached for 5 minutes so paging through one query asks the worker once."""
    key = (text, project, int(time.time() // 300))
    if key in _semantic_cache:
        return _semantic_cache[key]
    params = {"query": text, "format": "json", "limit": SEMANTIC_LIMIT}
    if project:
        params["projects"] = project
    try:
        with urlopen(f"{WORKER}/api/search?{urlencode(params)}", timeout=SEMANTIC_TIMEOUT) as r:
            data = json.load(r)
        result = {kind: [x["id"] for x in data.get(key_, []) if isinstance(x, dict) and "id" in x]
                  for key_, kind in WORKER_KINDS.items()}
    except (OSError, ValueError):
        return None  # not cached: try again next time
    if len(_semantic_cache) > 200:
        _semantic_cache.clear()
    _semantic_cache[key] = result
    return result


def fuse(con, keyword_hits, sem, fw, fp, limit=MAX_RANKED):
    """Reciprocal rank fusion of our keyword ranking with the worker's per-kind rankings. Worker results
    go through the same filters (mode, project, type, hidden). Returns [(rowid, -score, created)] best first."""
    score, created = {}, {}
    for rank, (rowid, _, ts, *_) in enumerate(keyword_hits, 1):
        score[rowid] = KEYWORD_WEIGHT / (RRF_K + rank)
        created[rowid] = ts
    for kind, ids in sem.items():
        if not ids:
            continue
        rows = con.execute(f"SELECT d.rowid, d.src_id, d.created_at_epoch FROM docs d WHERE {fw} AND d.kind = ? "
                           f"AND d.src_id IN ({','.join('?' * len(ids))})", fp + [kind] + ids).fetchall()
        by_src = {src: (rowid, ts) for rowid, src, ts in rows}
        rank = 0
        for src in ids:
            if src in by_src:
                rank += 1  # rank among results that pass our filters
                rowid, ts = by_src[src]
                score[rowid] = score.get(rowid, 0) + SEMANTIC_WEIGHT / (RRF_K + rank)
                created[rowid] = ts
    return sorted(((r, -sc, created[r]) for r, sc in score.items()), key=lambda h: (h[1], h[0]))[:limit]


def filters(kinds, project, otype, hidden):
    where, params = ["d.kind IN (%s)" % ",".join("?" * len(kinds))], list(kinds)
    if project:
        where.append("(d.project = ? OR d.merged_into_project = ?)")
        params += [project, project]
    if hidden:
        where.append("d.hidden = 0 AND COALESCE(d.project, '') NOT IN (%s)" % ",".join("?" * len(hidden)))
        params += list(hidden)
    if otype == "other":
        where.append("d.kind = 'observation' AND COALESCE(d.type, '') NOT IN (%s)" % ",".join("?" * len(MAIN_TYPES)))
        params += list(MAIN_TYPES)
    elif otype:
        where.append("d.kind = 'observation' AND d.type = ?")
        params.append(otype)
    return " AND ".join(where), params


DOC_COLS = ("rowid", "kind", "src_id", "project", "session", "platform_source", "type", "created_at_epoch", "title")


GROUP_SHOW = 3  # records shown per session when results are grouped
GROUP_POOL = 2000  # matches considered when grouping: the best 500 records often sit in a few big sessions


def find(q="", mode="everything", project="", otype="", sort="", page=1, size=25, hidden=HIDDEN_PROJECTS,
         details=True, use_semantic=True, group=False):
    """One search over the chosen record kinds. With a query: the best MAX_RANKED matches, by relevance
    ('best') or by date. Without one: everything, newest first, exact totals. page=-1 is the last page.
    group=True pages through sessions instead of records: each session is placed by its first match in
    the chosen order (best match, newest or oldest) and shows its top GROUP_SHOW matches; without a
    query, sessions come newest-active first with their latest records. `groups` then holds them.
    `semantic` in the result: True (worker results fused in), False (worker unavailable), None (not used:
    no query, turned off, or the query has phrases/exclusions, which ask for exact matches)."""
    mode = mode if mode in MODES else "everything"
    pool = GROUP_POOL if group else MAX_RANKED
    parsed = parse(q)
    used_semantic = None
    with closing(indexer.connect_index()) as con:
        expr, terms = match_expr(con, parsed)
        fw, fp = filters(MODES[mode], project, otype, hidden)
        if mode == "conversation":  # the user's own words: leave out subagent messages recorded as prompts
            fw += " AND NOT (d.kind = 'prompt' AND COALESCE(d.type, '') = 'agent')"
        if expr:
            sort = sort if sort in ("best", "newest", "oldest") else "best"
            # The index is stemmed, so "read only" also matches "readings only"; phrases are re-checked
            # against the text as written, from a wider candidate pool.
            exact = [re.compile(r"(?i)(?<!\w)" + r"\W+".join(map(re.escape, p.split())) + r"(?!\w)")
                     for p in parsed["phrases"]]
            hits = con.execute(
                f"SELECT d.rowid, bm25(docs_stem, {TITLE_WEIGHT}, 1.0), d.created_at_epoch, "
                f"{'d.title, d.body' if exact else 'NULL, NULL'} FROM docs_stem "
                f"JOIN docs d ON d.rowid = docs_stem.rowid WHERE docs_stem MATCH ? AND {fw} "
                f"ORDER BY 2 LIMIT ?", [expr] + fp + [pool * 10 if exact else pool]).fetchall()
            if exact:
                hits = [h for h in hits if all(rx.search(f"{h[3] or ''}\n{h[4] or ''}") for rx in exact)][:pool]
            elif use_semantic and not parsed["excludes"]:
                sem = semantic(" ".join(words(q)), project)
                used_semantic = sem is not None
                if sem:
                    hits = fuse(con, hits, sem, fw, fp, pool)
            if sort != "best":
                hits.sort(key=lambda h: (h[2], h[0]), reverse=sort == "newest")
            total, capped = len(hits), len(hits) == pool
        else:
            sort = "oldest" if sort == "oldest" else "newest"
            total, capped = con.execute(f"SELECT COUNT(*) FROM docs d WHERE {fw}", fp).fetchone()[0], False
        groups = None
        if group:
            grouped, total = group_page(con, hits if expr else None, fw, fp, sort, page, size)
            page, groups = grouped["page"], grouped["groups"]
            pages, offset = max(1, -(-total // size)), (page - 1) * size
            rowids = [r for g in groups for r in g["rowids"]]
        else:
            pages = max(1, -(-total // size))
            page = pages if page == -1 or page > pages else max(1, page)
            offset = (page - 1) * size
            if expr:
                rowids = [h[0] for h in hits[offset:offset + size]]
            else:
                order = "DESC" if sort == "newest" else "ASC"
                rowids = [r[0] for r in con.execute(
                    f"SELECT d.rowid FROM docs d WHERE {fw} ORDER BY d.created_at_epoch {order}, d.rowid {order} "
                    f"LIMIT ? OFFSET ?", fp + [size, offset])]
        items = fetch_docs(con, rowids)
        if expr and rowids:
            marks = {r[0]: r[1:] for r in con.execute(
                f"SELECT rowid, highlight(docs_stem, 0, ?, ?), snippet(docs_stem, 1, ?, ?, '…', 40) "
                f"FROM docs_stem WHERE docs_stem MATCH ? AND rowid IN ({','.join('?' * len(rowids))})",
                [HL_ON, HL_OFF, HL_ON, HL_OFF, expr] + rowids)}
            for it in items:
                it["title_hl"], it["snippet"] = marks.get(it["rowid"], (None, None))
    if details:
        add_details(items)
    if groups is not None:
        by_row = {it["rowid"]: it for it in items}
        for g in groups:
            g["items"] = [by_row[r] for r in g.pop("rowids") if r in by_row]
            g["project"] = g["items"][0]["project"] if g["items"] else None
    return {"mode": mode, "sort": sort, "semantic": used_semantic, "total": total, "capped": capped, "page": page, "pages": pages,
            "size": size, "first_index": offset + 1 if total else 0, "terms": terms, "query": parsed,
            "grouped": groups is not None, "groups": groups, "items": items}


def group_page(con, hits, fw, fp, sort, page, size):
    """One page of sessions. `hits` (ranked [(rowid, score, created, ...)]) for a query, None to browse.
    Records without a session stand alone. Returns ({"page", "groups": [{session, matches, first_epoch,
    last_epoch, rowids}]}, total sessions); page=-1 means the last page."""
    if hits is not None:
        info = {}
        ids = [h[0] for h in hits]
        for chunk in (ids[i:i + 900] for i in range(0, len(ids), 900)):
            info.update({r: (sess, ts) for r, sess, ts in con.execute(
                f"SELECT rowid, session, created_at_epoch FROM docs WHERE rowid IN ({','.join('?' * len(chunk))})", chunk)})
        by_session = {}  # insertion order = order of each session's first hit
        for rowid in ids:
            by_session.setdefault(info[rowid][0] or f"#{rowid}", []).append(rowid)
        total = len(by_session)
        pages = max(1, -(-total // size))
        page = pages if page == -1 or page > pages else max(1, page)
        keys = list(by_session)[(page - 1) * size: page * size]
        groups = []
        for k in keys:
            stamps = [info[r][1] for r in by_session[k] if info[r][1]]
            groups.append({"session": None if k.startswith("#") else k, "matches": len(by_session[k]),
                           "first_epoch": min(stamps, default=None), "last_epoch": max(stamps, default=None),
                           "rowids": by_session[k][:GROUP_SHOW]})
        return {"page": page, "groups": groups}, total
    key = "COALESCE(d.session, '#' || d.rowid)"
    total = con.execute(f"SELECT COUNT(DISTINCT {key}) FROM docs d WHERE {fw}", fp).fetchone()[0]
    pages = max(1, -(-total // size))
    page = pages if page == -1 or page > pages else max(1, page)
    order = "ASC" if sort == "oldest" else "DESC"
    edge = "MIN" if sort == "oldest" else "MAX"
    rows = con.execute(
        f"SELECT {key}, COUNT(*), MIN(d.created_at_epoch), MAX(d.created_at_epoch) FROM docs d WHERE {fw} "
        f"GROUP BY 1 ORDER BY {edge}(d.created_at_epoch) {order} LIMIT ? OFFSET ?",
        fp + [size, (page - 1) * size]).fetchall()
    groups = []
    for k, n, first, last in rows:
        if k.startswith("#"):
            rowids = [int(k[1:])]
        else:
            rowids = [r[0] for r in con.execute(
                f"SELECT d.rowid FROM docs d WHERE {fw} AND d.session = ? "
                f"ORDER BY d.created_at_epoch {order}, d.rowid {order} LIMIT ?", fp + [k, GROUP_SHOW])]
        groups.append({"session": None if k.startswith("#") else k, "matches": n, "first_epoch": first,
                       "last_epoch": last, "rowids": rowids})
    return {"page": page, "groups": groups}, total


def fetch_docs(con, rowids):
    if not rowids:
        return []
    rows = con.execute(f"SELECT {', '.join('d.' + c for c in DOC_COLS)} FROM docs d "
                       f"WHERE d.rowid IN ({','.join('?' * len(rowids))})", rowids).fetchall()
    by_id = {r[0]: dict(zip(DOC_COLS, r)) for r in rows}
    return [by_id[i] for i in rowids if i in by_id]


DETAIL_SQL = {
    "observation": "SELECT id, prompt_number, title, type, subtitle, narrative, facts, files_read, files_modified "
                   "FROM observations WHERE id IN (%s)",
    "summary": "SELECT id, prompt_number, request, investigated, learned, completed, next_steps, notes, files_edited "
               "FROM session_summaries WHERE id IN (%s)",
    "prompt": "SELECT id, prompt_number, prompt_text FROM user_prompts WHERE id IN (%s)",
}


def add_details(items):
    """Full fields for display, read from claude-mem.db (read-only)."""
    if not items:
        return
    with closing(indexer.connect_source()) as src:
        for kind, sql in DETAIL_SQL.items():
            ids = [it["src_id"] for it in items if it["kind"] == kind]
            if not ids:
                continue
            cur = src.execute(sql % ",".join("?" * len(ids)), ids)
            cols = [c[0] for c in cur.description]
            found = {r[0]: dict(zip(cols, r)) for r in cur.fetchall()}
            for it in items:
                if it["kind"] == kind:
                    it["detail"] = found.get(it["src_id"], {})


def projects(hidden=HIDDEN_PROJECTS):
    marks = ",".join("?" * len(hidden)) or "NULL"
    with closing(indexer.connect_index()) as con:
        rows = con.execute(
            "SELECT project, COUNT(*), MAX(created_at_epoch) FROM docs WHERE project IS NOT NULL "
            f"AND project NOT IN ({marks}) GROUP BY project ORDER BY 3 DESC", list(hidden)).fetchall()
    return [{"project": p, "n": n, "last": last} for p, n, last in rows]


# --- Session view: one session laid out turn by turn (a turn = one user prompt and what followed it).

NOTES_PER_TURN = 300  # a few turns hold hundreds of notes; the page folds them anyway

SESSION_TURNS_SQL = """
    SELECT 'observation', id, prompt_number FROM observations WHERE memory_session_id = :s
    UNION ALL SELECT 'summary', id, prompt_number FROM session_summaries WHERE memory_session_id = :s
    UNION ALL SELECT 'prompt', p.id, p.prompt_number FROM user_prompts p
        JOIN sdk_sessions ss ON ss.content_session_id = p.content_session_id WHERE ss.memory_session_id = :s"""


def session_view(session, turn=None, before=2, after=2):
    """Turns of `session` around `turn` (default: the first), with every visible record in them.
    Returns None if the session has no visible records (unknown, or all hidden)."""
    with closing(indexer.connect_index()) as con:
        flags = {(k, i): (hidden, typ, proj) for k, i, hidden, typ, proj in con.execute(
            "SELECT kind, src_id, hidden, type, project FROM docs WHERE session = ?", (session,))}
    visible = {key for key, (hidden, _, _) in flags.items() if not hidden}
    if not visible:
        return None
    with closing(indexer.connect_source()) as src:
        by_turn = {}
        for kind, rid, num in src.execute(SESSION_TURNS_SQL, {"s": session}):
            if (kind, rid) in visible:
                by_turn.setdefault(num or 0, []).append((kind, rid))
        turns = sorted(by_turn)
        at = turns.index(turn) if turn in by_turn else (
            next((i for i, t in enumerate(turns) if t > (turn or 0)), len(turns) - 1) if turn else 0)
        window = turns[max(0, at - max(0, before)): at + max(0, after) + 1]
        records = {}
        for kind, sql in DETAIL_SQL.items():
            ids = [rid for t in window for k, rid in by_turn[t] if k == kind]
            for chunk in (ids[i:i + 900] for i in range(0, len(ids), 900)):
                cur = src.execute(sql.replace("SELECT id,", "SELECT id, created_at_epoch,") % ",".join("?" * len(chunk)), chunk)
                cols = [c[0] for c in cur.description]
                for r in cur.fetchall():
                    records[(kind, r[0])] = dict(zip(cols, r))
    out_turns = []
    for t in window:
        group = {"turn": t, "prompts": [], "summaries": [], "notes": [], "notes_total": 0}
        for kind, rid in by_turn[t]:
            rec = records.get((kind, rid))
            if not rec:
                continue
            if kind == "prompt":
                rec["agent"] = flags[(kind, rid)][1] == "agent"
                group["prompts"].append(rec)
            elif kind == "summary":
                group["summaries"].append(rec)
            else:
                group["notes"].append(rec)
        for key in ("prompts", "summaries", "notes"):
            group[key].sort(key=lambda r: (r["created_at_epoch"] or 0, r["id"]))
        group["notes_total"] = len(group["notes"])
        group["notes"] = group["notes"][:NOTES_PER_TURN]
        stamps = [r["created_at_epoch"] for k in ("prompts", "summaries", "notes") for r in group[k] if r["created_at_epoch"]]
        group["at"] = min(stamps) if stamps else None
        out_turns.append(group)
    projects = [p for (h, _, p) in flags.values() if not h and p]
    with closing(indexer.connect_index()) as con:
        first, last, platform = con.execute(
            "SELECT MIN(created_at_epoch), MAX(created_at_epoch), MAX(platform_source) FROM docs "
            "WHERE session = ? AND hidden = 0", (session,)).fetchone()
    return {"session": session, "project": max(set(projects), key=projects.count) if projects else None,
            "platform_source": platform, "first_epoch": first, "last_epoch": last,
            "turn_numbers": turns, "focus_turn": turns[at] if turns else None,
            "has_earlier": bool(window) and window[0] != turns[0],
            "has_later": bool(window) and window[-1] != turns[-1], "turns": out_turns}
