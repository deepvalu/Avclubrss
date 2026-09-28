# A.V. Club weekly TV picks – RSS

Subscribe: https://deepvalu.github.io/avclubrss/feed.xml

`weeks.json` holds one entry per weekly "What's On" column; `build_feed.py` turns it into `feed.xml`. Updated every Sunday.

## MDBList sync

`sync_mdblist.py` adds every pick to the static MDBList list **A.V. Club Weekly Picks**. The GitHub Action in `.github/workflows/mdblist.yml` runs it whenever `weeks.json` changes, and again every Sunday.

- Needs the repo secret `MDBLIST_API_KEY`.
- `mdblist_matches.json` shows what each pick matched. Check any it got wrong.
- `mdblist_unmatched.txt` lists picks it couldn't find.
- To fix a pick, add it to `mdblist_overrides.json`, keyed by the exact text from `weeks.json`:
  - `{"search": "Better title", "type": "show"}` searches with a different title
  - `{"type": "show", "imdb": "tt1234567"}` uses an exact item
  - `null` skips the pick
- Live events like award shows and the Olympics are skipped automatically.
- Run it by hand from the Actions tab ("Sync MDBList" → Run workflow). Tick "dry run" to preview matches without adding anything.
