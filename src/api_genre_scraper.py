"""Spotify API genre scraper — waits for rate limit to clear, then runs.

Uses Spotify search API with token rotation. Searches specific genres
and extracts curator contact info from playlist descriptions.
Designed to run after rate limits expire.
"""

import csv
import html as html_mod
import os
import re
import sys
import time
import random
from datetime import datetime

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
INSTAGRAM_REGEX = re.compile(
    r"(?:instagram\.com/|(?:^|[\s|•·\-,])(?:ig|insta(?:gram)?)[:\s/@]+@?)([a-zA-Z0-9][a-zA-Z0-9_.]{2,29})",
    re.IGNORECASE | re.MULTILINE,
)
IG_STOPWORDS = {
    "for", "the", "and", "this", "that", "with", "from", "not", "are", "was",
    "but", "has", "had", "have", "will", "can", "all", "her", "his", "its",
    "our", "you", "com", "org", "net", "www", "http", "https",
    "reel", "reels", "explore", "stories", "p",
}
EMAIL_BLACKLIST = {
    "abuse@spotify.com", "support@spotify.com", "copyright@spotify.com",
    "privacy@spotify.com", "legal@spotify.com",
}

TOKEN_PLAYLISTS = [
    "37i9dQZF1DXcBWIGoYBM5M", "37i9dQZF1DX0XUsuxWHRQd",
    "37i9dQZF1DWXRqgorJj26U", "37i9dQZF1DX4sWSpwq3LiO",
    "37i9dQZF1DX1lVhptIYRda", "37i9dQZF1DXcF6B6QPhFDv",
    "37i9dQZF1DWY4xHQp97fN6", "37i9dQZF1DX4JAvHpjipBk",
    "37i9dQZF1DX10zKzsJ2jva", "37i9dQZF1DX76Wlfdnj7AP",
    "37i9dQZF1DWWQRwui0ExPn", "37i9dQZF1DWZeKCadgRdKQ",
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
]

# Genre keywords from user specification
GENRE_KEYWORDS = [
    "Study Beats", "Study Music", "Study Hip-Hop", "Focus Beats", "Deep Focus",
    "Brain Food", "Lo-Fi Study", "Homework Beats", "Study Session", "Late Night Study",
    "Jazz-Hop", "Jazz Hip-Hop", "Jazz Beats", "Nu Jazz", "Jazz Rap",
    "Jazzy Vibes", "Jazzy Beats", "Smooth Jazz Hop",
    "Chill Hop", "Chillhop Music", "Chill Beats", "Chill Vibes", "Relaxing Beats",
    "Mellow Beats", "Sunday Chill", "Afternoon Chill",
    "Hip-Hop", "Hip Hop Hits", "Hip-Hop Mix", "New Hip-Hop", "Hip-Hop Essentials",
    "Underground Hip-Hop", "Hip-Hop Bangers", "Hip-Hop Classics",
    "Conscious Hip-Hop", "Conscious Rap", "Thought-Provoking Rap", "Lyrical Hip-Hop",
    "Woke Hip-Hop", "Deep Hip-Hop", "Message Rap",
    "Rap", "Rap Caviar", "Rap Hits", "New Rap", "Rap Mix", "Rap Rotation",
    "Rap God", "Southern Rap", "East Coast Rap", "West Coast Rap", "Trap Rap", "Street Rap",
    "Pop Rap", "Pop Hip-Hop", "Rap Pop Crossover", "Mainstream Rap", "Radio Rap", "Pop Trap",
    "Neo-Soul", "Neo Soul Vibes", "Soul Music", "Modern Soul", "Soulful R&B",
    "Soul Sessions", "Soul Kitchen", "New Soul",
    "Latin Hip-Hop", "Latin Rap", "Spanish Hip-Hop", "Reggaeton Hip-Hop", "Urban Latino",
    "Latin Trap", "Trap Latino", "Spanish Rap", "Afrobeats Latin",
    "BoomBap", "Boom Bap Beats", "Old School Boom Bap", "Classic Boom Bap",
    "Underground Boom Bap", "Bedroom Boom Bap", "Bedroom Rap", "Bedroom Beats", "DIY Hip-Hop",
    "Pop Lo-Fi", "Lo-Fi Pop", "Lo-Fi Hits", "Lo-Fi Chill", "Lo-Fi Hip-Hop",
    "Lo-Fi Beats", "Lo-Fi Cafe", "Lo-Fi Girl", "Lo-Fi Aesthetic", "Cozy Lo-Fi",
    "Pop", "Pop Hits", "Pop Mix", "Indie Pop", "Alt Pop", "Pop Vibes",
    "Top Pop", "Feel Good Pop", "Bedroom Pop", "Sad Pop", "Dark Pop", "Dreamy Pop",
    "Alternative R&B", "Alt R&B", "Alternative Soul", "Experimental R&B",
    "Dark R&B", "Moody R&B", "R&B Vibes", "Unconventional R&B",
    "Indie R&B", "Independent R&B", "Underground R&B", "DIY R&B",
    "Bedroom R&B", "Soft R&B", "Chill R&B", "Mellow R&B", "Soulful Indie",
]


def build_keywords():
    """Generate search keywords from genre keywords."""
    keywords = []
    seen = set()
    for kw in GENRE_KEYWORDS:
        variants = [
            f"submit {kw} playlist",
            f"{kw} playlist submit",
            f"{kw} playlist email",
            f"{kw} curator email",
            f"{kw} accepting submissions",
            kw,  # Raw genre name
        ]
        for v in variants:
            vl = v.lower()
            if vl not in seen:
                seen.add(vl)
                keywords.append(v)
    return keywords


class TokenPool:
    def __init__(self):
        self.tokens = []
        self.idx = 0
        self.burned = set()

    def fill(self, count=4):
        s = requests.Session()
        s.verify = False
        for pid in random.sample(TOKEN_PLAYLISTS, min(count + 2, len(TOKEN_PLAYLISTS))):
            if len(self.tokens) >= count:
                break
            s.headers["User-Agent"] = random.choice(USER_AGENTS)
            try:
                resp = s.get(f"https://open.spotify.com/embed/playlist/{pid}", timeout=15)
                tokens = re.findall(r'"accessToken":"([^"]+)"', resp.text)
                if tokens and tokens[0] not in self.burned and tokens[0] not in self.tokens:
                    self.tokens.append(tokens[0])
            except Exception:
                continue
            time.sleep(0.5)
        print(f"  Token pool: {len(self.tokens)} tokens")

    def get(self):
        if not self.tokens:
            raise RuntimeError("No tokens")
        return self.tokens[self.idx % len(self.tokens)]

    def rotate(self):
        if len(self.tokens) <= 1:
            return False
        self.idx = (self.idx + 1) % len(self.tokens)
        return True

    def mark_burned(self, token):
        self.burned.add(token)
        self.tokens = [t for t in self.tokens if t != token]
        if self.tokens:
            self.idx = self.idx % len(self.tokens)

    def refresh_one(self):
        s = requests.Session()
        s.verify = False
        s.headers["User-Agent"] = random.choice(USER_AGENTS)
        pid = random.choice(TOKEN_PLAYLISTS)
        try:
            resp = s.get(f"https://open.spotify.com/embed/playlist/{pid}", timeout=15)
            tokens = re.findall(r'"accessToken":"([^"]+)"', resp.text)
            if tokens and tokens[0] not in self.burned and tokens[0] not in self.tokens:
                self.tokens.append(tokens[0])
                return True
        except Exception:
            pass
        return False


def extract_contacts(text):
    if not text:
        return [], []
    emails = EMAIL_REGEX.findall(text)
    emails = [e for e in emails if e.lower() not in EMAIL_BLACKLIST
              and not e.endswith((".png", ".jpg", ".svg", ".gif", ".css", ".js"))]
    raw_ig = INSTAGRAM_REGEX.findall(text)
    instagrams = [h for h in raw_ig if h.lower() not in IG_STOPWORDS and len(h) > 2]
    return list(set(emails)), list(set(instagrams))


FIELDNAMES = ["email", "instagram", "playlist_name", "playlist_url", "keyword",
              "description_snippet", "followers", "priority"]


def load_existing(filename="output.csv"):
    rows = []
    seen_contacts = set()
    seen_ids = set()
    try:
        with open(filename, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if "followers" not in row:
                    row["followers"] = ""
                if "priority" not in row:
                    row["priority"] = ""
                rows.append(row)
                url = row.get("playlist_url", "")
                if "/playlist/" in url:
                    seen_ids.add(url.split("/playlist/")[-1].split("?")[0])
                email = row.get("email", "").strip()
                ig = row.get("instagram", "").strip()
                if email:
                    seen_contacts.add(email.lower())
                if ig:
                    seen_contacts.add(ig.lower())
    except FileNotFoundError:
        pass
    return rows, seen_contacts, seen_ids


def save_csv(rows, filename="output.csv"):
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def save_run_csv(new_rows):
    if not new_rows:
        return None
    runs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runs")
    os.makedirs(runs_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = os.path.join(runs_dir, f"api_genre_run_{timestamp}.csv")
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(new_rows)
    return filename


def wait_for_api():
    """Poll Spotify API until rate limit clears."""
    s = requests.Session()
    s.verify = False
    s.headers["User-Agent"] = random.choice(USER_AGENTS)

    # Get a token
    resp = s.get(f"https://open.spotify.com/embed/playlist/{TOKEN_PLAYLISTS[0]}", timeout=15)
    token = re.findall(r'"accessToken":"([^"]+)"', resp.text)[0]

    print("Waiting for Spotify API rate limit to clear...")
    while True:
        resp = s.get(
            "https://api.spotify.com/v1/search",
            headers={"Authorization": f"Bearer {token}"},
            params={"q": "test", "type": "playlist", "limit": 1},
            timeout=15,
        )
        if resp.status_code == 200:
            print("API is available!")
            return True
        elif resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 300))
            mins = retry_after // 60
            print(f"  Still rate limited. Retry-After: {retry_after}s (~{mins}m). Checking again in 5m...")
            time.sleep(300)  # Check every 5 minutes
        elif resp.status_code == 401:
            # Token expired, get new one
            resp2 = s.get(f"https://open.spotify.com/embed/playlist/{random.choice(TOKEN_PLAYLISTS)}", timeout=15)
            tokens = re.findall(r'"accessToken":"([^"]+)"', resp2.text)
            if tokens:
                token = tokens[0]
            time.sleep(5)
        else:
            print(f"  Unexpected status: {resp.status_code}")
            time.sleep(60)


def api_search_keyword(pool, keyword, seen_ids, seen_contacts, session):
    """Search one keyword, extract contacts from descriptions."""
    results = []
    offset = 0
    total_playlists = 0
    rate_limited = False

    while offset < 1000:
        token = pool.get()
        try:
            resp = session.get(
                "https://api.spotify.com/v1/search",
                headers={"Authorization": f"Bearer {token}"},
                params={"q": keyword, "type": "playlist", "limit": 50, "offset": offset},
                timeout=15,
            )
        except requests.RequestException:
            time.sleep(2)
            continue

        if resp.status_code == 200:
            data = resp.json().get("playlists", {})
            items = data.get("items", [])
            if not items:
                break

            total_playlists += len(items)

            for pl in items:
                if not pl or not pl.get("id"):
                    continue
                pid = pl["id"]
                if pid in seen_ids:
                    continue
                seen_ids.add(pid)

                desc = html_mod.unescape(pl.get("description", "") or "")
                emails, instagrams = extract_contacts(desc)

                if not emails and not instagrams:
                    continue

                email_str = ", ".join(emails)
                ig_str = ", ".join(instagrams)
                contact_key = (email_str or ig_str).lower()
                if contact_key in seen_contacts:
                    continue
                seen_contacts.add(contact_key)

                playlist_url = pl.get("external_urls", {}).get(
                    "spotify", f"https://open.spotify.com/playlist/{pid}")

                results.append({
                    "email": email_str,
                    "instagram": ig_str,
                    "playlist_name": pl.get("name", ""),
                    "playlist_url": playlist_url,
                    "keyword": keyword,
                    "description_snippet": desc[:100].replace("\n", " "),
                    "followers": "",
                    "priority": "",
                })

            offset += 50
            time.sleep(random.uniform(2, 4))

            if offset % 150 == 0:
                pool.rotate()

        elif resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 30))
            if retry_after > 120:
                print(f"    Rate limited ({retry_after}s). Refreshing tokens and waiting 60s...")
                pool.tokens.clear()
                pool.burned.clear()
                time.sleep(60)
                pool.fill(4)
                if not pool.tokens:
                    rate_limited = True
                    break
                continue
            if pool.rotate():
                time.sleep(3)
                continue
            print(f"    Rate limited ({retry_after}s), waiting...")
            time.sleep(min(retry_after + 2, 60))
            pool.fill(4)
            if pool.tokens:
                continue
            rate_limited = True
            break

        elif resp.status_code == 401:
            pool.mark_burned(token)
            if not pool.tokens:
                pool.fill(3)
                if not pool.tokens:
                    break
        else:
            break

    return results, total_playlists, rate_limited


def main():
    target_total = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 1500

    # Wait for rate limit to clear
    wait_for_api()

    keywords = build_keywords()
    random.shuffle(keywords)

    existing_rows, seen_contacts, seen_ids = load_existing()
    print(f"\nLoaded {len(existing_rows)} existing entries ({len(seen_contacts)} unique contacts)")
    print(f"Loaded {len(seen_ids)} known playlist IDs to skip")
    print(f"Target: {target_total} total | {len(keywords)} keywords\n")

    session = requests.Session()
    session.verify = False
    session.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json",
    })

    pool = TokenPool()
    print("Building token pool...")
    pool.fill(4)
    if not pool.tokens:
        print("ERROR: No tokens")
        return

    all_rows = list(existing_rows)
    new_rows = []
    total_new = 0
    consecutive_rate_limits = 0

    for i, keyword in enumerate(keywords):
        if len(all_rows) >= target_total:
            print(f"\nReached target of {target_total}+ total contacts!")
            break

        print(f"\n[{i+1}/{len(keywords)}] '{keyword}' (total: {len(all_rows)}, +{total_new} this run)")

        results, total_pl, rate_limited = api_search_keyword(
            pool, keyword, seen_ids, seen_contacts, session
        )

        all_rows.extend(results)
        new_rows.extend(results)
        total_new += len(results)

        for r in results:
            contact = r["email"] or r["instagram"]
            print(f"    HIT: {r['playlist_name']} | {contact}")

        count = save_csv(all_rows)
        print(f"  Searched {total_pl} playlists => +{len(results)} new | {count} total ({total_new} this run)")

        if rate_limited:
            consecutive_rate_limits += 1
            if consecutive_rate_limits >= 5:
                print("\n  Persistent rate limiting. Pausing 120s...")
                time.sleep(120)
                pool.tokens.clear()
                pool.burned.clear()
                pool.fill(4)
                consecutive_rate_limits = 0
            elif consecutive_rate_limits >= 3:
                print("\n  Heavy rate limiting. Pausing 60s...")
                time.sleep(60)
                pool.fill(4)
                consecutive_rate_limits = 0
            else:
                time.sleep(15)
                pool.refresh_one()
        else:
            consecutive_rate_limits = 0
            if i % 5 == 4:
                pool.refresh_one()
            time.sleep(random.uniform(3, 6))

    count = save_csv(all_rows)
    run_file = save_run_csv(new_rows)
    print(f"\n{'=' * 60}")
    print(f"DONE! +{total_new} new contacts this run. {count} total in output.csv")
    if run_file:
        print(f"New contacts saved to {run_file}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
