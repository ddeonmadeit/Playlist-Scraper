"""Fast Spotify playlist curator scraper.

Uses Spotify API search with token rotation and conservative pacing.
Search results include playlist descriptions — no per-playlist API calls needed.
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


class TokenPool:
    """Pool of anonymous Spotify tokens with rotation on rate limits."""

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


def api_search_keyword(pool, keyword, seen_ids, seen_contacts, session):
    """Search one keyword across multiple pages, extracting contacts from descriptions.

    Conservative pacing: 2s between requests, rotate tokens proactively.
    """
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
                })

            offset += 50
            # Conservative pacing to avoid rate limits
            time.sleep(2)

            # Proactively rotate token every 3 pages
            if offset % 150 == 0:
                pool.rotate()

        elif resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 30))
            if pool.rotate():
                # Try next token immediately
                time.sleep(1)
                continue
            # All tokens hit — short wait then try fresh token
            if retry_after <= 30:
                print(f"    Rate limited ({retry_after}s), waiting...")
                time.sleep(retry_after + 2)
                pool.refresh_one()
                continue
            else:
                print(f"    Heavy rate limit ({retry_after}s), stopping keyword")
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


def load_existing(filename="output.csv"):
    rows = []
    seen_contacts = set()
    seen_ids = set()
    try:
        with open(filename, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
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
    fieldnames = ["email", "instagram", "playlist_name", "playlist_url", "keyword", "description_snippet"]
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def save_new_contacts_csv(new_rows):
    """Save only the new contacts from this run to a timestamped CSV in the runs/ folder."""
    if not new_rows:
        return None
    runs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runs")
    os.makedirs(runs_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = os.path.join(runs_dir, f"new_contacts_{timestamp}.csv")
    fieldnames = ["email", "instagram", "playlist_name", "playlist_url", "keyword", "description_snippet"]
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(new_rows)
    return filename


def main():
    keywords = [
        # High-yield submit keywords
        "submit rap playlist", "submit hip hop playlist",
        "submit lofi playlist", "submit R&B playlist",
        "submit beats playlist", "submit neo soul playlist",
        "submit boom bap playlist", "submit jazz hop playlist",
        "submit chill hop playlist", "submit study beats playlist",
        "submit bedroom pop playlist", "submit conscious rap playlist",
        "submit alternative hip hop", "submit indie hip hop",
        "submit lo-fi beats playlist", "submit soul playlist",
        "submit afrobeats playlist", "submit latin rap playlist",
        "submit pop rap playlist", "submit lo-fi pop playlist",
        "submit alternative R&B", "submit indie R&B",
        "submit Latin hip hop", "submit jazz rap playlist",
        # Email-focused queries
        "rap playlist email submit", "hip hop playlist email submit",
        "lofi playlist email submit", "R&B playlist email submit",
        "rap playlist curators email", "hip hop playlist curators contact",
        # Broader patterns
        "submit your music rap", "submit your song hip hop",
        "accepting submissions rap playlist", "accepting submissions hip hop",
        "send beats playlist", "promote rap music playlist",
        "underground hip hop submit", "independent artist playlist submit",
        "new artist rap playlist", "unsigned artist playlist submit",
        "indie rap playlist submit", "chill rap playlist submit",
        "fresh hip hop playlist", "hidden gems rap playlist",
        "undiscovered rap playlist", "small artist rap playlist",
        # More genres
        "submit trap playlist", "submit drill playlist",
        "submit phonk playlist", "submit cloud rap playlist",
        "submit emo rap playlist", "submit UK rap playlist",
        "submit reggaeton playlist", "submit dancehall playlist",
        "submit funk playlist", "submit gospel rap playlist",
        "submit christian hip hop", "submit southern rap playlist",
        "submit west coast rap", "submit east coast rap",
        "submit midwest rap", "submit Atlanta rap playlist",
        # Additional high-quality patterns
        "playlist submission rap", "playlist submission hip hop",
        "playlist submission R&B", "playlist submission lofi",
        "indie playlist submit", "underground playlist submit",
        "submit music playlist", "submit track playlist",
        "curator playlist rap", "curator playlist hip hop",
        # --- NEW: genre expansion ---
        "submit pop playlist", "submit rock playlist",
        "submit indie playlist", "submit electronic playlist",
        "submit EDM playlist", "submit house playlist",
        "submit techno playlist", "submit dubstep playlist",
        "submit drum and bass playlist", "submit trance playlist",
        "submit ambient playlist", "submit synthwave playlist",
        "submit vaporwave playlist", "submit chillwave playlist",
        "submit future bass playlist", "submit bass music playlist",
        "submit country playlist", "submit folk playlist",
        "submit blues playlist", "submit jazz playlist",
        "submit metal playlist", "submit punk playlist",
        "submit hardcore playlist", "submit emo playlist",
        "submit screamo playlist", "submit post punk playlist",
        "submit shoegaze playlist", "submit dream pop playlist",
        "submit garage rock playlist", "submit psychedelic playlist",
        "submit grunge playlist", "submit ska playlist",
        "submit reggae playlist", "submit dub playlist",
        "submit latin playlist", "submit salsa playlist",
        "submit bachata playlist", "submit cumbia playlist",
        "submit corridos playlist", "submit regional mexicano playlist",
        "submit K-pop playlist", "submit J-pop playlist",
        "submit anime playlist", "submit Bollywood playlist",
        "submit Afro pop playlist", "submit amapiano playlist",
        "submit grime playlist", "submit UK garage playlist",
        "submit jungle playlist", "submit breakbeat playlist",
        "submit hardstyle playlist", "submit progressive house playlist",
        "submit deep house playlist", "submit tech house playlist",
        "submit melodic techno playlist", "submit minimal techno playlist",
        "submit disco playlist", "submit nu disco playlist",
        "submit funk house playlist", "submit tropical house playlist",
        # --- NEW: activity/mood playlists (high contact rate) ---
        "submit workout playlist", "submit gym playlist",
        "submit running playlist", "submit yoga playlist",
        "submit meditation playlist", "submit sleep playlist",
        "submit study playlist", "submit focus playlist",
        "submit coding playlist", "submit driving playlist",
        "submit road trip playlist", "submit party playlist",
        "submit pregame playlist", "submit chill playlist",
        "submit relaxing playlist", "submit sad playlist",
        "submit happy playlist", "submit motivational playlist",
        "submit wedding playlist", "submit summer playlist",
        # --- NEW: curator/contact patterns ---
        "playlist curator submit music", "playlist curator email contact",
        "spotify playlist submit your track", "spotify playlist accepting submissions",
        "submit song to playlist", "send your track playlist",
        "music submission playlist spotify", "playlist curators accepting music",
        "indie music playlist submission", "new music playlist submit",
        "emerging artist playlist submit", "unsigned artist playlist",
        "fresh finds playlist submit", "discovery playlist submit",
        "new release playlist submit", "debut artist playlist",
        # --- NEW: email/contact in description ---
        "playlist email gmail", "playlist submission email",
        "playlist contact submit", "playlist demo submission",
        "submit demo playlist", "playlist promo submit",
        "playlist promotion submit", "add your song playlist",
        "get on playlist submit", "playlist placement submit",
        # --- NEW: more niche genres ---
        "submit gospel playlist", "submit worship playlist",
        "submit classical playlist", "submit orchestra playlist",
        "submit acoustic playlist", "submit singer songwriter playlist",
        "submit spoken word playlist", "submit poetry playlist",
        "submit podcast playlist", "submit comedy playlist",
        "submit gaming playlist", "submit twitch playlist",
        "submit NCS playlist", "submit copyright free playlist",
        "submit royalty free playlist", "submit background music playlist",
        "submit coffee shop playlist", "submit lounge playlist",
        "submit downtempo playlist", "submit trip hop playlist",
        "submit instrumental playlist", "submit piano playlist",
        "submit guitar playlist", "submit saxophone playlist",
        "submit covers playlist", "submit remix playlist",
        "submit mashup playlist", "submit live music playlist",
        # --- NEW: geographic patterns ---
        "submit Nigerian playlist", "submit South African playlist",
        "submit Brazilian playlist", "submit French rap playlist",
        "submit German rap playlist", "submit Spanish playlist",
        "submit Australian playlist", "submit Canadian playlist",
        "submit Japanese playlist", "submit Korean playlist",
        "submit African playlist", "submit Caribbean playlist",
        "submit European playlist", "submit Asian playlist",
    ]

    target = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 200

    existing_rows, seen_contacts, seen_ids = load_existing()
    print(f"Loaded {len(existing_rows)} existing entries ({len(seen_contacts)} unique contacts)")
    print(f"Loaded {len(seen_ids)} known playlist IDs to skip")
    print(f"Target: {target} new contacts\n")

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
        print("ERROR: No tokens. Spotify may be blocking this IP.")
        return

    all_rows = list(existing_rows)
    new_rows_this_run = []
    total_new = 0
    consecutive_rate_limits = 0

    for i, keyword in enumerate(keywords):
        if total_new >= target:
            print(f"\nReached target of {target} new contacts!")
            break

        print(f"\n[{i+1}/{len(keywords)}] '{keyword}'")

        results, total_pl, rate_limited = api_search_keyword(
            pool, keyword, seen_ids, seen_contacts, session
        )

        all_rows.extend(results)
        new_rows_this_run.extend(results)
        total_new += len(results)

        for r in results:
            contact = r["email"] or r["instagram"]
            print(f"    HIT: {r['playlist_name']} | {contact}")

        count = save_csv(all_rows)
        print(f"  Searched {total_pl} playlists => +{len(results)} new | {count} total ({total_new} this run)")

        if rate_limited:
            consecutive_rate_limits += 1
            if consecutive_rate_limits >= 3:
                print("\n  Heavy rate limiting. Pausing 60s to recover...")
                time.sleep(60)
                pool.fill(4)
                consecutive_rate_limits = 0
            else:
                time.sleep(10)
                pool.refresh_one()
        else:
            consecutive_rate_limits = 0
            # Proactive token refresh every 5 keywords
            if i % 5 == 4:
                pool.refresh_one()
            time.sleep(random.uniform(3, 5))

    count = save_csv(all_rows)
    run_file = save_new_contacts_csv(new_rows_this_run)
    print(f"\n{'=' * 60}")
    print(f"DONE! +{total_new} new contacts this run. {count} total in output.csv")
    if run_file:
        print(f"New contacts saved to {run_file}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
