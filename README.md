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
- Each item is added in the order of the week it was featured, so sorting the list by "date added" follows the articles. A show featured again in a later week moves to the top.
- To clear the list and re-add everything in order, run the workflow with "rebuild" ticked.
- Live events like award shows and the Olympics are skipped automatically.
- Run it by hand from the Actions tab ("Sync MDBList" → Run workflow). Tick "dry run" to preview matches without adding anything.

## 2026 Released Series (MDBList)

`sync_released.py` mirrors [Dracid's 2026 Released Series](https://dracid77.github.io/lists/released-series) into the static MDBList list **2026 Released Series**, every day (`.github/workflows/released.yml`). It uses the IMDb IDs from that site's catalog feed, so there's no title matching. New shows are added one at a time, oldest release first, so sorting the list by "date added" follows release order. Shows dropped from the source list are removed. Run it by hand from Actions → "Sync 2026 Released Series"; tick "rebuild" to clear and re-add everything in order.
