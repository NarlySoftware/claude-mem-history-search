"""A demo claude-mem.db of invented history, for screenshots and for trying the page without claude-mem:

    python3 -I tests/demo.py /tmp/demo.db
    HISTORY_SEARCH_INDEX=/tmp/demo-index.db python3 -I server.py --db /tmp/demo.db --port 37691

Every project, prompt and note in it is made up.
"""
import json, os, sqlite3, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixture import SCHEMA  # noqa: E402

START_MS = 1782864000000  # 2026-07-01, in milliseconds like claude-mem
HOUR = 3600 * 1000

# (project, days after START, [turn, ...]); a turn is (prompt, summary, [observation, ...]).
# summary: (request, investigated, learned, completed, next_steps)
# observation: (type, title, subtitle, narrative, [facts], [files modified])
SESSIONS = [
    ("invoice-api", 3, [
        ("Users are getting logged out every few minutes on staging. Why did the login break?",
         ("Find why staging sessions expire within minutes",
          "Token issue and refresh paths in auth/jwt.py; staging and production clock settings.",
          "The staging host's clock ran 4 minutes fast, so fresh tokens looked nearly expired. Production "
          "was unaffected because its hosts use NTP.",
          "Confirmed the clock drift and reproduced the logout locally by skewing time.",
          "Allow a small clock skew when validating tokens."),
         [("bugfix", "Login tokens rejected on staging due to clock drift", "auth/jwt.py",
           "Tokens were issued with a 5 minute lifetime and validated with zero leeway. The staging host's clock "
           "was 4 minutes ahead, so most tokens failed validation soon after login.",
           ["Staging clock was 4 minutes fast", "JWT validation used leeway=0"], ["auth/jwt.py"]),
          ("discovery", "Staging hosts were not running NTP", "infra",
           "The staging image was built without the time sync service, unlike production.",
           ["Production image enables chrony", "Staging image did not"], [])]),
        ("Add leeway for clock skew and a test for it",
         ("Tolerate small clock skew in token validation",
          "PyJWT's leeway option and the existing auth tests.",
          "A 30 second leeway covers normal drift without meaningfully extending token life.",
          "Added leeway=30 and a test that skews the clock by 20 and 60 seconds.",
          "Turn on time sync in the staging image."),
         [("change", "JWT validation now allows 30 s of clock skew", "auth/jwt.py",
           "Validation passes leeway=30. Tokens skewed by 20 s pass; 60 s fail as expected.",
           ["leeway=30", "New test: test_clock_skew"], ["auth/jwt.py", "tests/test_auth.py"])]),
    ]),
    ("invoice-api", 9, [
        ("The PDF export is slow for big invoices, can you look into it?",
         ("Speed up PDF export for large invoices",
          "Profiled export of a 2,000-line invoice.",
          "Most of the time went to re-loading the font file for every page.",
          "Cached the loaded fonts; export of the large invoice went from 14 s to 1.2 s.",
          "Consider streaming very large exports."),
         [("refactor", "Fonts loaded once per export instead of per page", "export/pdf.py",
           "The renderer re-read the TTF file on each page. Loading it once and reusing it removed 90% of the time.",
           ["14 s -> 1.2 s for 2,000 lines"], ["export/pdf.py"]),
          ("decision", "Keep server-side PDF rendering", "export",
           "Client-side rendering was considered and dropped: invoices must match the archived copy byte for byte.",
           ["Archived PDFs are the legal record"], [])]),
    ]),
    ("weather-app", 15, [
        ("Where did we decide how often to refresh the forecast?",
         ("Settle the forecast refresh interval",
          "Provider rate limits and battery impact of background refresh.",
          "The provider allows 1,000 calls a day per key; refreshing every 15 minutes in the foreground and "
          "hourly in the background stays well under it.",
          "Set foreground refresh to 15 minutes and background to 60.",
          "Show the time of the last refresh in the UI."),
         [("decision", "Forecast refresh: 15 min foreground, 60 min background", "sync/schedule.ts",
           "Chosen to stay under the provider's daily limit and keep background battery use low.",
           ["Provider limit: 1,000 calls/day", "Background refresh hourly"], ["sync/schedule.ts"])]),
        ("Dark mode colors look washed out on the radar map",
         ("Fix low-contrast radar colors in dark mode",
          "The radar tile palette and the map's dark style.",
          "The radar layer used 60% opacity, which looked fine on light maps but faded on dark ones.",
          "Raised opacity to 85% in dark mode and picked a brighter palette for light rain.",
          "Check the legend matches the new palette."),
         [("bugfix", "Radar layer too faint on the dark map", "map/RadarLayer.tsx",
           "Opacity now depends on the color scheme: 0.6 light, 0.85 dark.",
           ["Opacity 0.6 -> 0.85 in dark mode"], ["map/RadarLayer.tsx"]),
          ("feature", "Radar legend follows the color scheme", "map/Legend.tsx",
           "The legend reads the same palette as the radar layer, so they always match.",
           [], ["map/Legend.tsx"])]),
    ]),
    ("weather-app", 28, [
        ("Push notifications stopped arriving on iOS after the update",
         ("Restore iOS push notifications after the 2.3 update",
          "APNs responses in the server log and the app's entitlements.",
          "The 2.3 build was signed with the development push entitlement, so production APNs rejected "
          "every token with BadDeviceToken.",
          "Switched the release build to the production entitlement and re-registered devices on launch.",
          "Add a release checklist item for the push entitlement."),
         [("bugfix", "Release build used the development push entitlement", "ios/App.entitlements",
           "aps-environment was 'development' in the release configuration. APNs answered BadDeviceToken.",
           ["APNs error: BadDeviceToken", "aps-environment must be 'production' for release"],
           ["ios/App.entitlements"])]),
    ]),
    ("dotfiles", 20, [
        ("Set up a shell alias to search my notes folder quickly",
         ("Add a fast notes search alias",
          "ripgrep options and the notes folder layout.",
          "rg with --smart-case and a glob for markdown files is fast enough that no index is needed.",
          "Added `notes` as a shell function wrapping rg.",
          "None."),
         [("feature", "notes: ripgrep over ~/notes", "zsh/functions.zsh",
           "notes <words> searches markdown files in ~/notes with smart case and shows two lines of context.",
           ["rg --smart-case -g '*.md' -C 2"], ["zsh/functions.zsh"])]),
    ]),
    ("blog", 33, [
        ("Images on the blog load slowly on phones",
         ("Speed up blog images on mobile",
          "Image sizes and formats on the five heaviest posts.",
          "Images were served at full camera resolution; responsive sizes cut the page weight by 80%.",
          "Generated 480/960/1600 px variants at build time and added srcset.",
          "Lazy-load images below the fold."),
         [("change", "Responsive image variants generated at build time", "build/images.js",
           "Each image now has 480, 960 and 1600 px versions in WebP, chosen with srcset.",
           ["Page weight -80% on mobile"], ["build/images.js", "layouts/post.html"])]),
    ]),
]


def build(path):
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    for n, (project, day, turns) in enumerate(SESSIONS, 1):
        sid = f"demo-{n}"
        con.execute("INSERT INTO sdk_sessions (content_session_id, memory_session_id, project) VALUES (?,?,?)",
                    (f"content-{sid}", sid, project))
        t = START_MS + day * 24 * HOUR + 10 * HOUR
        for turn, (prompt, summary, observations) in enumerate(turns, 1):
            t += 5 * 60 * 1000
            con.execute("INSERT INTO user_prompts (content_session_id, prompt_number, prompt_text, created_at, "
                        "created_at_epoch) VALUES (?,?,?,?,?)", (f"content-{sid}", turn, prompt, "", t))
            for typ, title, subtitle, narrative, facts, files in observations:
                t += 2 * 60 * 1000
                con.execute(
                    "INSERT INTO observations (memory_session_id, project, type, title, subtitle, facts, narrative, "
                    "concepts, files_read, files_modified, prompt_number, created_at, created_at_epoch) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (sid, project, typ, title, subtitle, json.dumps(facts), narrative, "[]", json.dumps(files),
                     json.dumps(files), turn, "", t))
            t += 60 * 1000
            request, investigated, learned, completed, next_steps = summary
            con.execute(
                "INSERT INTO session_summaries (memory_session_id, project, request, investigated, learned, completed, "
                "next_steps, files_read, files_edited, prompt_number, created_at, created_at_epoch) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (sid, project, request, investigated, learned, completed, next_steps, "[]", "[]", turn, "", t))
    con.commit()
    con.close()


if __name__ == "__main__":
    build(sys.argv[1])
