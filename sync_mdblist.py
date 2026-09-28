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


def norm(s):
    s = s.lower().replace("&", "and").replace("’", "'")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"^(the|a|an) ", "", re.sub(r"\s+", " ", s).strip())
    return s


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
    lists = api("GET", "/lists/user")
    for l in lists:
        if norm(l.get("name", "")) == norm(LIST_NAME):
            if l.get("dynamic"):
                sys.exit(f'"{LIST_NAME}" is a dynamic list; it must be a static list.')
            return l["id"]
    names = ", ".join(l.get("name", "?") for l in lists) or "none"
    sys.exit(f'No list named "{LIST_NAME}" on your account (found: {names}).')


def match(title, year, want_type=None):
    kind = {"movie": "movie", "show": "show"}.get(want_type, "any")
    res = api("GET", f"/search/{kind}", {"query": title}).get("search", [])
    q = norm(title)
    exact = [r for r in res if norm(r.get("title", "")) == q]
    close = [r for r in res if norm(r.get("title", "")).startswith(q + " ") or q.startswith(norm(r.get("title", "")) + " ")]
    pool = exact or close
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
            "exact": bool(exact), "ambiguous": len(pool) > 1}


def main():
    if not KEY:
        sys.exit("MDBLIST_API_KEY is not set.")
    weeks = load("weeks.json", [])
    overrides = load("mdblist_overrides.json", {})
    matches = load("mdblist_matches.json", {})
    unmatched = []

    for w in weeks:
        year = int(w["start"][:4])
        for pick in w["picks"]:
            o = overrides.get(pick, "none")
            if o is None:
                matches.pop(pick, None)
                continue
            if isinstance(o, dict) and ("imdb" in o or "tmdb" in o):
                prev = matches.get(pick, {})
                same = all(prev.get(k) == v for k, v in o.items())
                matches[pick] = dict(o, synced=prev.get("synced", False) and same, source="override")
                continue
            searched = isinstance(o, dict) and "search" in o
            if (pick in matches and (not searched or matches[pick].get("search") == o["search"])) \
                    or (EVENT_WORDS.search(pick) and not searched):
                continue
            title = o["search"] if searched else clean_title(pick)
            m = match(title, year, o.get("type") if searched else None)
            if m and searched:
                m["search"] = o["search"]
            time.sleep(0.3)
            if m:
                matches[pick] = dict(m, synced=False)
                flag = "" if m["exact"] and not m["ambiguous"] else "  (check this one)"
                print(f"matched  {pick!r} -> {m['title']} ({m['year']}, {m['type']}){flag}")
            else:
                unmatched.append(f"{w['start']}  {pick}  [searched: {title}]")

    pending = {p: m for p, m in matches.items() if not m.get("synced")}
    body = {"movies": [], "shows": []}
    for m in pending.values():
        idkey = "imdb" if m.get("imdb") else "tmdb"
        entry = {idkey: m[idkey]}
        group = body["movies" if m["type"] == "movie" else "shows"]
        if entry not in group:
            group.append(entry)

    if pending and not DRY:
        list_id = find_list_id()
        res = api("POST", f"/lists/{list_id}/items/add", body=body)
        print("MDBList response:", json.dumps(res))
        for p in pending:
            matches[p]["synced"] = True
    print(f"{len(pending)} item(s) {'would be ' if DRY else ''}sent; {len(unmatched)} unmatched.")

    with open("mdblist_matches.json", "w") as f:
        json.dump(dict(sorted(matches.items())), f, indent=1, ensure_ascii=False)
    with open("mdblist_unmatched.txt", "w") as f:
        f.write("Picks the sync couldn't match. Add fixes to mdblist_overrides.json.\n\n")
        f.write("\n".join(unmatched) + ("\n" if unmatched else ""))


if __name__ == "__main__":
    main()
