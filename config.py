"""Where things are: claude-mem's database, its worker's address, our own index, and local settings.

claude-mem's locations are worked out the way claude-mem 13.40 does it, so a stock install needs no setup:
- data folder: env CLAUDE_MEM_DATA_DIR, then CLAUDE_MEM_DATA_DIR in ~/.claude-mem/settings.json
  (top level or inside an "env" object), then ~/.claude-mem
- worker: env CLAUDE_MEM_WORKER_HOST / CLAUDE_MEM_WORKER_PORT, then the same keys in
  <data folder>/settings.json, then 127.0.0.1 and port 37700 + (uid % 100) (37777 without a uid)
HISTORY_SEARCH_DB, HISTORY_SEARCH_INDEX and HISTORY_SEARCH_LOCAL point at another database, index or
local settings file (server.py --db sets the first; the tests set all three).
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PORT = 37690  # outside claude-mem's worker range (37700-37799), so the two never collide


def read_json(path):
    try:
        with open(os.path.expanduser(path)) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def setting(name, settings):
    """env, then settings.json (top level, then a nested "env" object). Empty values count as unset."""
    env = settings.get("env") if isinstance(settings.get("env"), dict) else {}
    for v in (os.environ.get(name), settings.get(name), env.get(name)):
        if v not in (None, ""):
            return str(v)
    return None


def data_dir():
    return os.path.expanduser(setting("CLAUDE_MEM_DATA_DIR", read_json("~/.claude-mem/settings.json"))
                              or "~/.claude-mem")


def db_path():
    return os.path.expanduser(os.environ.get("HISTORY_SEARCH_DB") or os.path.join(data_dir(), "claude-mem.db"))


def worker_port():
    port = setting("CLAUDE_MEM_WORKER_PORT", read_json(os.path.join(data_dir(), "settings.json")))
    if port and port.isdigit():
        return int(port)
    return 37700 + os.getuid() % 100 if hasattr(os, "getuid") else 37777


def worker_url():
    host = setting("CLAUDE_MEM_WORKER_HOST", read_json(os.path.join(data_dir(), "settings.json"))) or "127.0.0.1"
    return f"http://{host}:{worker_port()}"


def index_path():
    return os.environ.get("HISTORY_SEARCH_INDEX") or os.path.join(HERE, "data", "index.db")


def local():
    """Optional local settings (local.json next to this file; see local.example.json)."""
    return read_json(os.environ.get("HISTORY_SEARCH_LOCAL") or os.path.join(HERE, "local.json"))
