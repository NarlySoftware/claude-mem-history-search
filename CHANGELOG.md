# Changelog

## 2026-10-24: first public release

- Ranked search over claude-mem's observations, summaries and prompts: filler words dropped, Porter
  stemming, bm25 with titles weighted, `"phrases"` and `-exclusions`, typo alternatives from your own
  vocabulary.
- Meaning search through claude-mem's worker (Chroma), merged by reciprocal rank fusion.
- Conversation / Notes / Everything modes; project, type and order filters; exact paging.
- Session view (a result's session, turn by turn) and grouping by session.
- Phone layout, light/dark/auto theme, bookmarkable URLs, keyboard shortcuts.
- Finds claude-mem's database and worker the way claude-mem does; optional `local.json` hiding rules.
- macOS LaunchAgent installer; optional Tailscale access limited to your own login.
- Tests on a made-up database; WebKit phone checks; a search-quality benchmark for your own queries.
