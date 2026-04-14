#!/usr/bin/env python3
"""
LA28 Ticket Availability Updater
Scrapes Reddit (r/LosAngeles, r/olympics, r/2028olympics) and
DuckDuckGo news for reports on sold-out / limited / available events.
Writes updates to availability.json — only escalates status (never de-escalates).
"""

import json, re, time, requests
from datetime import datetime, timezone
from pathlib import Path

AVAIL_FILE = Path(__file__).parent.parent / "availability.json"

SUBREDDITS  = ["LosAngeles", "olympics", "2028olympics", "la28"]
SEARCH_TERMS = ["LA28 ticket", "Olympics 2028 ticket", "la28 sold out", "LA28 availability"]

STATUS_RANK = {"soldout": 5, "premium": 4, "limited": 3, "available": 2, "free": 1, "unknown": 0}

SOLD_OUT_WORDS  = ["sold out", "no tickets", "unavailable", "all gone", "no inventory",
                   "completely sold", "sold through", "zero tickets"]
PREMIUM_WORDS   = ["only premium", "thousand dollar", "premium only", "no cheap tickets",
                   "high tier only", "only expensive", "budget seats gone"]
LIMITED_WORDS   = ["limited", "going fast", "few left", "almost gone", "selling fast",
                   "low inventory", "hard to find", "nearly sold"]
AVAILABLE_WORDS = ["still available", "tickets available", "can still buy", "in stock",
                   "seats available", "still on sale", "can buy now", "plenty of tickets"]

SPORT_ALIASES = {
    "opening ceremony":    "Opening Ceremony",
    "closing ceremony":    "Closing Ceremony",
    "track and field":     "Track & Field — Finals",
    "track & field":       "Track & Field — Finals",
    "athletics":           "Track & Field — Finals",
    "track prelim":        "Track & Field — Prelims",
    "swimming final":      "Swimming — Finals",
    "swimming prelim":     "Swimming — Prelims",
    "swim final":          "Swimming — Finals",
    "swimming":            "Swimming — Finals",
    "gymnastics":          "Gymnastics — Artistic",
    "artistic gymnastics": "Gymnastics — Artistic",
    "rhythmic gymnastics": "Gymnastics — Rhythmic",
    "basketball final":    "Basketball — Medals",
    "basketball medal":    "Basketball — Medals",
    "basketball":          "Basketball — Prelims",
    "soccer":              "Soccer — Prelims",
    "women's soccer":      "Soccer — Prelims",
    "football":            "Soccer — Prelims",
    "volleyball":          "Volleyball — Indoor",
    "beach volleyball":    "Beach Volleyball",
    "surfing": "Surfing", "surf": "Surfing",
    "diving":  "Diving",
    "tennis":  "Tennis",
    "flag football":    "Flag Football",
    "cricket":          "Cricket (T20)",
    "lacrosse":         "Lacrosse (Sixes)",
    "skateboarding":    "Skateboarding",
    "skate":            "Skateboarding",
    "breaking":         "Breaking (Breakdancing)",
    "breakdancing":     "Breaking (Breakdancing)",
    "equestrian":       "Equestrian",
    "golf":             "Golf",
    "rugby":            "Rugby Sevens",
    "water polo":       "Water Polo",
    "handball":         "Handball",
    "boxing":           "Boxing",
    "sport climbing":   "Sport Climbing",
    "climbing":         "Sport Climbing",
}

def reddit_posts():
    posts = []
    headers = {"User-Agent": "LA28TicketBot/1.0 (github.com/reedberg99/la28-planner)"}
    for sub in SUBREDDITS:
        for term in SEARCH_TERMS[:2]:   # stay polite
            try:
                r = requests.get(
                    f"https://www.reddit.com/r/{sub}/search.json",
                    headers=headers,
                    params={"q": term, "sort": "new", "limit": 20, "t": "month"},
                    timeout=12,
                )
                if r.status_code == 200:
                    for p in r.json()["data"]["children"]:
                        d = p["data"]
                        posts.append({
                            "title": d.get("title", ""),
                            "text":  d.get("selftext", ""),
                            "source": f"reddit.com/r/{sub}",
                        })
                time.sleep(0.6)
            except Exception as exc:
                print(f"  Reddit {sub}: {exc}")
    return posts

def ddg_snippets():
    snippets = []
    for q in ["LA28 tickets sold out 2026", "LA28 Olympic ticket availability"]:
        try:
            r = requests.get(
                "https://api.duckduckgo.com/",
                params={"q": q, "format": "json", "no_html": 1, "skip_disambig": 1},
                timeout=10,
            )
            if r.status_code == 200:
                d = r.json()
                for item in [d.get("AbstractText","")] + [t.get("Text","") for t in d.get("RelatedTopics",[])[:6]]:
                    if item:
                        snippets.append({"title": q, "text": item, "source": "DuckDuckGo"})
            time.sleep(0.4)
        except Exception as exc:
            print(f"  DDG: {exc}")
    return snippets

def infer_status(text):
    t = text.lower()
    if any(w in t for w in SOLD_OUT_WORDS):  return "soldout"
    if any(w in t for w in PREMIUM_WORDS):   return "premium"
    if any(w in t for w in LIMITED_WORDS):   return "limited"
    if any(w in t for w in AVAILABLE_WORDS): return "available"
    return None

def extract_mentions(docs):
    found = {}
    for doc in docs:
        full = (doc["title"] + " " + doc["text"]).lower()
        for alias, canonical in SPORT_ALIASES.items():
            if alias not in full:
                continue
            sentences = [s.strip() for s in re.split(r'[.!?\n]', full) if alias in s and len(s.strip()) > 10]
            for sent in sentences:
                status = infer_status(sent)
                if status:
                    if canonical not in found:
                        found[canonical] = {"status": status, "notes": [], "sources": []}
                    old = STATUS_RANK.get(found[canonical]["status"], 0)
                    new = STATUS_RANK.get(status, 0)
                    if new > old:
                        found[canonical]["status"] = status
                    if len(found[canonical]["notes"]) < 2:
                        found[canonical]["notes"].append(sent[:120])
                    src = doc["source"]
                    if src not in found[canonical]["sources"]:
                        found[canonical]["sources"].append(src)
                    break
    return found

def main():
    now = datetime.now(timezone.utc)
    print(f"[{now.isoformat()}] Fetching data…")

    with open(AVAIL_FILE) as f:
        current = json.load(f)
    events = current["events"]

    docs = reddit_posts() + ddg_snippets()
    print(f"  {len(docs)} documents collected")

    mentions = extract_mentions(docs)
    print(f"  Sport mentions found: {list(mentions.keys()) or 'none'}")

    updated = {}
    changed = []
    for sport, data in events.items():
        if sport in mentions:
            m = mentions[sport]
            old_rank = STATUS_RANK.get(data["status"], 0)
            new_rank = STATUS_RANK.get(m["status"], 0)
            if new_rank > old_rank:
                src = ", ".join(m["sources"][:2])
                note_text = "; ".join(m["notes"][:1])
                updated[sport] = {
                    "status": m["status"],
                    "note": f"{note_text} ({src}, {now.strftime('%b %d %Y')})",
                }
                changed.append(f"{sport}: {data['status']} → {m['status']}")
            else:
                updated[sport] = data
        else:
            updated[sport] = data

    output = {
        "lastUpdated": now.strftime("%Y-%m-%d"),
        "source": f"Auto-scraped: Reddit ({', '.join('r/'+s for s in SUBREDDITS)}), DuckDuckGo — {now.strftime('%b %d, %Y')}",
        "drop": current.get("drop", "Drop 1"),
        "events": updated,
    }

    with open(AVAIL_FILE, "w") as f:
        json.dump(output, f, indent=2)

    if changed:
        print(f"  Changes: {changed}")
    else:
        print("  No status changes this run.")
    print("Done.")

if __name__ == "__main__":
    main()
