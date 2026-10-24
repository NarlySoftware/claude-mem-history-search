# User guide

The page opens on everything claude-mem has recorded, newest first. Type in the search box to search,
or just browse.

![The search page](img/search.png)

## What's in your history

claude-mem records three kinds of things, and the page shows each with a coloured badge:

| Badge | What it is |
|---|---|
| **you** | A prompt you typed. *turn N* is its place in the session. |
| **agent** | A message a subagent sent back, recorded by claude-mem as a prompt |
| **summary** | claude-mem's digest of one turn: what was asked, investigated, learned, completed and planned next |
| **discovery**, **change**, **feature**, **bugfix**, **decision**, **refactor** | Observations: the notes claude-mem takes while the assistant works. Anything with another type shows a grey badge. |

The assistant's replies aren't stored word for word by claude-mem. The summaries and observations are
the record of its side.

## Searching

Type a question or a few words. Results update as you type, and Return searches straight away.

- Filler words are ignored, so *"where did we talk about the export being slow"* searches for *export*
  and *slow*.
- A record doesn't need every word; the more it has, and the rarer they are, the higher it ranks.
- `"exact phrase"` must appear as written. `-word` leaves out records containing that word.
- Close misspellings are also tried.

[Search syntax](search.md) has the full rules. The ✕ in the box clears it and goes back to browsing.

## Modes

| Mode | Searches | Use it for |
|---|---|---|
| **Conversation** | Your prompts and the per-turn summaries | "What did I ask, and what came of it?" Subagent messages are left out. |
| **Notes** | Observations and summaries | The detail of what was found and changed |
| **Everything** | All of the above | The default |

## Filters and order

- **Meaning:** also find results by meaning, using claude-mem's worker (adds about half a second). On by
  default. Turn it off for purely word-based results. If the worker isn't running, the count line says
  "meaning search unavailable" and you get word matches only.
- **Group by session:** see [below](#group-by-session).
- **Project:** one project's records. Records from projects that claude-mem merged into this one are
  included. Projects are listed most recently active first, with their record counts.
- **Type:** observations of one type, or *other* for every type outside the main six. Choosing a type
  shows observations only. Conversation mode hides this filter.
- **Order:** *Best match* (the default when searching), *Newest first* (the default when browsing) or
  *Oldest first*. Sorting a search by date keeps the same matches and only changes their order.
- **Per page:** 10, 25, 50 or 100.

A search keeps its best 500 matches. The count says so ("1–25 of the 500 best matches"). Add words or
filters to narrow it down. Browsing without a search pages through everything, with exact totals.

On a phone the filters fold away behind **Filters**, which shows how many are active. The line under
the search box names them.

## Results

Each result shows its badge, date, project and title. For a search, it also shows the passage that
matched, with your words highlighted. Click or tap a result to open its full detail:

- **observations:** narrative, facts, files read and files modified;
- **summaries:** investigated, learned, completed, next steps, notes and files edited;
- **prompts:** the full text.

Records from tools other than Claude Code show the tool's name next to the project (claude-mem records
other agents too).

## Session view

![Session view](img/session.png)

**Show in session →** in an opened result shows the whole session it came from, laid out by turn. Each
turn holds your prompt, its summary, and its observations, folded under "N notes". The turn with your
result has a blue edge on the left, and the result itself is outlined.

- **↑ Earlier turns** and **Later turns ↓** load five more turns at a time.
- **← Results** or your browser's back button returns to the search exactly as you left it.
- Typing a new search leaves the session view.

## Group by session

![Grouped by session](img/grouped.png)

With **Group by session** on, you get one card per session instead of one per record. Each card shows
the session's project, how many matches it has, its dates and its best three matches. **Open session →**
goes to the session view at the best match.

This is often the quickest way to find a conversation: the right session tends to rank high even when
the single best record is somewhere else. When searching, sessions are ranked by their best match among
the top 2,000. When browsing, they're ordered by most recent activity.

## Keyboard

| Key | |
|---|---|
| `/` | Jump to the search box |
| `Esc` | Leave the search box |
| `←` `→` | Previous / next page |
| `Home` `End` | First / last page |

You can also type a page number in the box between the arrows.

## Links and bookmarks

The address bar keeps the current search, so you can bookmark it, share it between your own devices or
use the back button. For example:

```
http://localhost:37690/#q=export+slow&mode=notes&sort=newest
http://localhost:37690/#session=<session id>&turn=3
```

| Search parameters | Session view parameters |
|---|---|
| `q`, `mode`, `project`, `type`, `sort`, `size`, `page`, `meaning=0`, `group=1` | `session`, `turn`, `hl=<kind>:<id>` (the record to outline) |

## Theme

The button at the top right cycles **Auto** (follows your device), **Light** and **Dark**. The choice is
saved in that browser only.

## On a phone

![Phone layout](img/phone.png)

The layout adapts below 640 px wide. The title, Filters and theme sit on top, the search box goes full
width under them, and paging is at the bottom of the results. Text fields use 16 px text, so iOS Safari
doesn't zoom in when you tap them. To reach it from your phone, see
[Other devices](install.md#other-devices).
