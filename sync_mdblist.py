"""Sync the A.V. Club weekly picks in weeks.json into a static MDBList list.

Env:
  MDBLIST_API_KEY   (required) your MDBList API key
  MDBLIST_LIST_ID   (optional) numeric list id; otherwise found by name
  MDBLIST_LIST_NAME (optional) defaults to "A.V. Club Weekly Picks"
  DRY_RUN=1         (optional) match titles but don't add anything

Files:
  mdblist_overrides.json  hand fixes, keyed by the exact pick text from weeks.json:
                            {"search": "Other title", "type": "show"|"movie"}  search differently
                            {"type": "show"|"movie", "imdb": "tt..."}           exact item
                            null                                                skip the pick
  mdblist_matches.json    cache written by this script (what each pick matched, and whether it's synced)
  mdblist_unmatched.txt   picks that couldn't be matched on the last run
"""
import json, os, re, sys, time, urllib.parse, urllib.request

API = "https://api.mdblist.com"
KEY = os.environ.get("MDBLIST_API_KEY", "")
LIST_NAME = os.environ.get("MDBLIST_LIST_NAME", "A.V. Club Weekly Picks")
DRY = os.environ.get("DRY_RUN") == "1"
REBUILD = os.environ.get("REBUILD") == "1"   # clear the list and re-add everything week by week

# Picks that are live events / ceremonies, not something MDBList can hold.
EVENT_WORDS = re.compile(
    r"\b(awards?|olympics|super bowl|ceremony|oscars|grammy|emmy|tony awards|culture awards|livestream)\b", re.I)


def load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def clean_title(pick):
    """'Paradise, season 2 (Hulu)' -> 'Paradise'."""
    t = re.sub(r"\s*\([^)]*\)\s*$", "", pick)          # trailing (Network)
    t = t.split(" / ")[0]                               # 'A / B' -> 'A'
    t = re.sub(r",\s*(final season|season \d+.*|vol\..*)$", "", t, flags=re.I)
    t = re.sub(r"\s+(series|season|limited series)?\s*(\d+\s*)?finale$", "", t, flags=re.I)
    t = re.sub(r"\s+season\s+\d+$", "", t, flags=re.I)
    t = re.sub(r"\s+(special|double episode|movie)$", "", t, flags=re.I)
    return t.strip()


def norm(s, keep_article=False):
    s = s.lower().replace("&", "and").replace("’", "'")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s if keep_article else re.sub(r"^(the|a|an) ", "", s)


def api(method, path, params=None, body=None):
    params = dict(params or {}, apikey=KEY)
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", "User-Agent": "avclubrss-sync"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:
                time.sleep(10)
                continue
            raise RuntimeError(f"{method} {path} -> HTTP {e.code}: {e.read()[:300]!r}")


def find_list_id():
    if os.environ.get("MDBLIST_LIST_ID"):
        return int(os.environ["MDBLIST_LIST_ID"])
    return find_list_id_by_name(LIST_NAME)


def find_list_id_by_name(name):
    lists = api("GET", "/lists/user")
    for l in lists:
        if norm(l.get("name", "")) == norm(name):
            if l.get("dynamic"):
                sys.exit(f'"{name}" is a dynamic list; it must be a static list.')
            return l["id"]
    names = ", ".join(l.get("name", "?") for l in lists) or "none"
    sys.exit(f'No list named "{name}" on your account (found: {names}).')


def match(title, year, want_type=None, want_year=None):
    kind = {"movie": "movie", "show": "show"}.get(want_type, "any")
    res = api("GET", f"/search/{kind}", {"query": title}).get("search", [])
    if want_year:
        res = [r for r in res if r.get("year") == want_year]
    q, qa = norm(title), norm(title, True)
    strict = [r for r in res if norm(r.get("title", ""), True) == qa]
    exact = [r for r in res if norm(r.get("title", "")) == q]
    # Longer/shorter titles only count if they're recent (avoids "Wolf" -> "Wolf Like Me").
    close = [] if want_year else [r for r in res if (r.get("year") or 0) >= year - 1 and (
        norm(r.get("title", "")).startswith(q + " ") or q.startswith(norm(r.get("title", "")) + " "))]
    pool = strict or exact or close
    if not pool:
        return None
    # Prefer TV shows (the column is mostly TV), then the most recent release
    # not after the pick's year (new shows, reboots), then the higher rated.
    pool.sort(key=lambda r: (r.get("type") != "movie", (r.get("year") or 0) <= year,
                             r.get("year") or 0, r.get("score") or 0), reverse=True)
    r = pool[0]
    ids = r.get("ids", {})
    typ = "movie" if r.get("type") == "movie" else "show"
    item = {"imdb": ids["imdbid"]} if ids.get("imdbid") else ({"tmdb": ids["tmdbid"]} if ids.get("tmdbid") else None)
    if not item:
        return None
    return {"type": typ, **item, "title": r.get("title"), "year": r.get("year"),
            "exact": bool(strict or exact), "ambiguous": len(pool) > 1}


def key_of(m):
    idkey = "imdb" if m.get("imdb") else "tmdb"
    return ("movies" if m["type"] == "movie" else "shows", idkey, str(m[idkey]))


def body_for(keys):
    body = {"movies": [], "shows": []}
    for group, idkey, val in sorted(set(keys), key=str):
        body[group].append({idkey: int(val) if idkey == "tmdb" else val})
    return body


def main():
    if not KEY:
        sys.exit("MDBLIST_API_KEY is not set.")
    weeks = load("weeks.json", [])
    overrides = load("mdblist_overrides.json", {})
    old = load("mdblist_matches.json", {})
    matches, unmatched, removed = {}, [], []

    for w in weeks:
        year = int(w["start"][:4])
        for pick in w["picks"]:
            prev = old.get(pick)
            o = overrides.get(pick, "none")
            if o is None or (o == "none" and EVENT_WORDS.search(pick)):
                if prev and prev.get("synced"):
                    removed.append(prev)
                continue
            o = o if isinstance(o, dict) else None
            if prev and "override" not in prev:              # cache from before overrides were tracked
                prev["override"] = o if o and prev.get("search") == o.get("search") and "year" not in o \
                    else (None if "search" not in prev else "legacy")
            if prev and prev.get("override") == o:          # already resolved the same way
                matches[pick] = dict(prev, week=w["start"])
                continue
            if o and ("imdb" in o or "tmdb" in o):
                m = {"type": o.get("type", "show"), **{k: o[k] for k in ("imdb", "tmdb") if k in o}}
            else:
                title = o["search"] if o and "search" in o else clean_title(pick)
                m = match(title, year, (o or {}).get("type"), (o or {}).get("year"))
                time.sleep(0.3)
                if not m:
                    unmatched.append(f"{w['start']}  {pick}  [searched: {title}]")
                    if prev and prev.get("synced"):
                        removed.append(prev)
                    continue
                flag = "" if m["exact"] and not m["ambiguous"] else "  (check this one)"
                print(f"matched  {pick!r} -> {m['title']} ({m['year']}, {m['type']}){flag}")
            m["override"] = o
            m["week"] = w["start"]
            m["synced"] = bool(prev and prev.get("synced") and key_of(prev) == key_of(m))
            if prev and prev.get("synced") and not m["synced"]:
                removed.append(prev)
            matches[pick] = m

    # Each item sits on the list at the latest week it was featured. MDBList stamps
    # "date added" itself, so items are added one week at a time, oldest first.
    state = {tuple(k.split("|")): v for k, v in load("mdblist_state.json", {}).items()}
    if not state:  # first run with state tracking: everything synced so far is on the list
        state = {key_of(m): "" for m in list(old.values()) + list(matches.values()) if m.get("synced")}
    want = {}
    for m in matches.values():
        want[key_of(m)] = max(want.get(key_of(m), ""), m["week"])
    on_list = set(state) | {key_of(m) for m in removed if m.get("synced")}

    if REBUILD:
        to_remove = on_list
        to_add = dict(want)
    else:
        to_remove = {k for k in on_list if k not in want or state.get(k, "") < want[k]}
        to_add = {k: wk for k, wk in want.items() if k not in state or state[k] < wk}
    to_remove &= on_list

    if (to_add or to_remove) and not DRY:
        list_id = find_list_id()
        if to_remove:
            res = api("POST", f"/lists/{list_id}/items/remove", body=body_for(to_remove))
            print("removed:", json.dumps(res))
            for k in to_remove:
                state.pop(k, None)
        for wk in sorted(set(to_add.values())):
            batch = [k for k, v in to_add.items() if v == wk]
            res = api("POST", f"/lists/{list_id}/items/add", body=body_for(batch))
            print(f"added week {wk}:", json.dumps(res))
            for k in batch:
                state[k] = wk
            time.sleep(2)
        for m in matches.values():
            m["synced"] = True
        with open("mdblist_state.json", "w") as f:
            json.dump({"|".join(map(str, k)): v for k, v in sorted(state.items(), key=lambda x: (x[1], str(x[0])))},
                      f, indent=1)
    print(f"{len(to_add)} to add, {len(to_remove)} to remove{' (dry run)' if DRY else ''}; "
          f"{len(unmatched)} unmatched.")

    if not DRY:
        with open("mdblist_matches.json", "w") as f:
            json.dump(dict(sorted(matches.items())), f, indent=1, ensure_ascii=False)
    with open("mdblist_unmatched.txt", "w") as f:
        f.write("Picks the sync couldn't match. Add fixes to mdblist_overrides.json.\n\n")
        f.write("\n".join(unmatched) + ("\n" if unmatched else ""))


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
