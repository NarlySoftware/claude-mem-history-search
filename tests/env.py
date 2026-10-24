"""Test setup; import it before indexer, search or server. By default the tests run against a small
made-up claude-mem.db (tests/fixture.py) in a temporary folder, the same on any machine, with no worker.
HISTORY_SEARCH_TESTS=live runs them against your real claude-mem database and worker instead (read-only;
our index in data/ is topped up).
"""
import atexit, json, os, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), HERE]
LIVE = os.environ.get("HISTORY_SEARCH_TESTS") == "live"

if not LIVE:
    import fixture  # noqa: E402
    tmp = tempfile.mkdtemp(prefix="history-search-test-")
    atexit.register(shutil.rmtree, tmp, True)
    fixture.build(os.path.join(tmp, "claude-mem.db"))
    with open(os.path.join(tmp, "local.json"), "w") as f:
        json.dump(fixture.LOCAL, f)
    os.environ.update(HISTORY_SEARCH_DB=os.path.join(tmp, "claude-mem.db"),
                      HISTORY_SEARCH_INDEX=os.path.join(tmp, "index.db"),
                      HISTORY_SEARCH_LOCAL=os.path.join(tmp, "local.json"),
                      CLAUDE_MEM_WORKER_PORT="9")  # nothing listens there: keyword-only unless a test fakes one

import indexer  # noqa: E402
indexer.sync()
