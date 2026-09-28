"""Mirror Dracid's "2026 Released Series" list into a static MDBList list.

Source: https://dracid77.github.io/lists/released-series (its Stremio catalog JSON,
which carries IMDb IDs, newest release first).

Env:
  MDBLIST_API_KEY            (required)
  RELEASED_LIST_NAME         MDBList list name, default "2026 Released Series"
  RELEASED_LIST_ID           numeric list id (optional, skips the name lookup)
  RELEASED_CATALOG           catalog URL (optional)
  DRY_RUN=1                  show what would change, change nothing
  REBUILD=1                  clear the list and re-add everything in release order

State: released_state.json  IMDb IDs currently on the MDBList list, in the order added.
"""
import json, os, sys, time, urllib.request

import sync_mdblist as mdb

CATALOG = os.environ.get("RELEASED_CATALOG",
                         "https://dracid77.github.io/lists/addon/catalog/series/released-series")
LIST_NAME = os.environ.get("RELEASED_LIST_NAME", "2026 Released Series")
STATE = "released_state.json"
DRY = os.environ.get("DRY_RUN") == "1"
REBUILD = os.environ.get("REBUILD") == "1"


def fetch_catalog():
    """All items, newest first, as [{'id': 'tt..', 'name': ..}]."""
    items, skip = [], 0
    while True:
        url = f"{CATALOG}.json" if skip == 0 else f"{CATALOG}/skip={skip}.json"
        req = urllib.request.Request(url, headers={"User-Agent": "avclubrss-sync"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                metas = json.load(r).get("metas", [])
        except urllib.error.HTTPError as e:
            if e.code == 404 and skip:
                break
            raise
        if not metas:
            break
        items += [{"id": m["id"], "name": m.get("name", "")} for m in metas if str(m.get("id", "")).startswith("tt")]
        skip += len(metas)
    seen, out = set(), []
    for it in items:
        if it["id"] not in seen:
            seen.add(it["id"])
            out.append(it)
    return out


def main():
    if not mdb.KEY:
        sys.exit("MDBLIST_API_KEY is not set.")
    items = fetch_catalog()
    if len(items) < 20:
        sys.exit(f"Source catalog returned only {len(items)} items; not touching the list.")
    names = {it["id"]: it["name"] for it in items}
    want = [it["id"] for it in reversed(items)]          # oldest release first
    state = mdb.load(STATE, [])
    on_list = set(state)

    to_remove = on_list if REBUILD else on_list - set(want)
    to_add = want if REBUILD else [i for i in want if i not in on_list]
    print(f"source: {len(items)} series; add {len(to_add)}, remove {len(to_remove)}"
          f"{' (dry run)' if DRY else ''}{' (rebuild)' if REBUILD else ''}")
    for i in to_add[-15:]:
        print("  +", names[i], i)
    for i in list(to_remove)[:15]:
        print("  -", i)
    if DRY or not (to_add or to_remove):
        return

    list_id = int(os.environ["RELEASED_LIST_ID"]) if os.environ.get("RELEASED_LIST_ID") \
        else mdb.find_list_id_by_name(LIST_NAME)
    if to_remove:
        res = mdb.api("POST", f"/lists/{list_id}/items/remove",
                      body={"shows": [{"imdb": i} for i in sorted(to_remove)]})
        print("removed:", json.dumps(res))
        state = [i for i in state if i not in to_remove]
    # One at a time, oldest first, so MDBList's "date added" follows release order.
    for n, i in enumerate(to_add, 1):
        mdb.api("POST", f"/lists/{list_id}/items/add", body={"shows": [{"imdb": i}]})
        state.append(i)
        if n % 25 == 0:
            print(f"  added {n}/{len(to_add)}")
            with open(STATE, "w") as f:
                json.dump(state, f, indent=0)
        time.sleep(1.1)
    with open(STATE, "w") as f:
        json.dump(state, f, indent=0)
    print(f"done: {len(state)} on list")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        if e.code not in (None, 0):
            print(f"::error::{e.code}")
        raise
    except Exception as e:
        print(f"::error::{type(e).__name__}: {e}")
        raise
