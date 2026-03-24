"""Genre-focused Spotify playlist curator scraper.

Uses DuckDuckGo to find playlists, then Spotify internal wg endpoint
to get descriptions (bypasses API rate limits). Extracts emails and IGs.
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
from ddgs import DDGS

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
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
]

# ── All genre keywords from user specification ───────────────────────────
GENRE_KEYWORDS = [
    # Study Beats
    "Study Beats", "Study Music", "Study Hip-Hop", "Focus Beats", "Deep Focus",
    "Brain Food", "Lo-Fi Study", "Homework Beats", "Study Session", "Late Night Study",
    # Jazz-Hop
    "Jazz-Hop", "Jazz Hip-Hop", "Jazz Beats", "Nu Jazz", "Jazz Rap",
    "Jazzy Vibes", "Jazzy Beats", "Smooth Jazz Hop",
    # Chill Hop
    "Chill Hop", "Chillhop Music", "Chill Beats", "Chill Vibes", "Relaxing Beats",
    "Mellow Beats", "Sunday Chill", "Afternoon Chill",
    # Hip-Hop
    "Hip-Hop", "Hip Hop Hits", "Hip-Hop Mix", "New Hip-Hop", "Hip-Hop Essentials",
    "Underground Hip-Hop", "Hip-Hop Bangers", "Hip-Hop Classics",
    # Conscious Hip-Hop
    "Conscious Hip-Hop", "Conscious Rap", "Thought-Provoking Rap", "Lyrical Hip-Hop",
    "Woke Hip-Hop", "Deep Hip-Hop", "Message Rap",
    # Rap
    "Rap", "Rap Caviar", "Rap Hits", "New Rap", "Rap Mix", "Rap Rotation",
    "Rap God", "Southern Rap", "East Coast Rap", "West Coast Rap", "Trap Rap", "Street Rap",
    # Pop Rap
    "Pop Rap", "Pop Hip-Hop", "Rap Pop Crossover", "Mainstream Rap", "Radio Rap", "Pop Trap",
    # Neo-Soul
    "Neo-Soul", "Neo Soul Vibes", "Soul Music", "Modern Soul", "Soulful R&B",
    "Soul Sessions", "Soul Kitchen", "New Soul",
    # Latin Hip-Hop
    "Latin Hip-Hop", "Latin Rap", "Spanish Hip-Hop", "Reggaeton Hip-Hop", "Urban Latino",
    "Latin Trap", "Trap Latino", "Spanish Rap", "Afrobeats Latin",
    # BoomBap / Bedroom
    "BoomBap", "Boom Bap Beats", "Old School Boom Bap", "Classic Boom Bap",
    "Underground Boom Bap", "Bedroom Boom Bap", "Bedroom Rap", "Bedroom Beats", "DIY Hip-Hop",
    # Pop Lo-Fi
    "Pop Lo-Fi", "Lo-Fi Pop", "Lo-Fi Hits", "Lo-Fi Chill", "Lo-Fi Hip-Hop",
    "Lo-Fi Beats", "Lo-Fi Cafe", "Lo-Fi Girl", "Lo-Fi Aesthetic", "Cozy Lo-Fi",
    # Pop
    "Pop", "Pop Hits", "Pop Mix", "Indie Pop", "Alt Pop", "Pop Vibes",
    "Top Pop", "Feel Good Pop", "Bedroom Pop", "Sad Pop", "Dark Pop", "Dreamy Pop",
    # Alternative R&B
    "Alternative R&B", "Alt R&B", "Alternative Soul", "Experimental R&B",
    "Dark R&B", "Moody R&B", "R&B Vibes", "Unconventional R&B",
    # Indie R&B
    "Indie R&B", "Independent R&B", "Underground R&B", "DIY R&B",
    "Bedroom R&B", "Soft R&B", "Chill R&B", "Mellow R&B", "Soulful Indie",
]


def build_search_queries():
    """Generate DDG search queries from genre keywords."""
    queries = []
    seen = set()

    # Submission-focused variants (highest yield)
    for kw in GENRE_KEYWORDS:
        variants = [
            f"site:open.spotify.com/playlist {kw} submit",
            f"site:open.spotify.com/playlist {kw} email",
            f"site:open.spotify.com/playlist {kw}",
        ]
        for v in variants:
            vl = v.lower()
            if vl not in seen:
                seen.add(vl)
                queries.append((v, kw))

    # Extra high-yield patterns
    extras = [
        ("site:open.spotify.com/playlist submit lofi playlist email", "Lo-Fi Submit"),
        ("site:open.spotify.com/playlist submit hip hop playlist email", "Hip-Hop Submit"),
        ("site:open.spotify.com/playlist submit rap playlist email", "Rap Submit"),
        ("site:open.spotify.com/playlist submit R&B playlist email", "R&B Submit"),
        ("site:open.spotify.com/playlist submit neo soul playlist", "Neo-Soul Submit"),
        ("site:open.spotify.com/playlist submit boom bap playlist", "BoomBap Submit"),
        ("site:open.spotify.com/playlist submit chill beats", "Chill Beats Submit"),
        ("site:open.spotify.com/playlist submit jazz beats", "Jazz Beats Submit"),
        ("site:open.spotify.com/playlist submit indie pop", "Indie Pop Submit"),
        ("site:open.spotify.com/playlist submit bedroom pop", "Bedroom Pop Submit"),
        ("site:open.spotify.com/playlist submit conscious rap", "Conscious Rap Submit"),
        ("site:open.spotify.com/playlist submit latin rap", "Latin Rap Submit"),
        ("site:open.spotify.com/playlist submit pop rap", "Pop Rap Submit"),
        ("site:open.spotify.com/playlist accepting submissions hip hop", "Hip-Hop Accepting"),
        ("site:open.spotify.com/playlist accepting submissions rap", "Rap Accepting"),
        ("site:open.spotify.com/playlist accepting submissions lofi", "Lo-Fi Accepting"),
        ("site:open.spotify.com/playlist underground hip hop submit", "Underground HH"),
        ("site:open.spotify.com/playlist independent artist playlist email", "Indie Artist"),
        ("site:open.spotify.com/playlist hidden gems playlist submit", "Hidden Gems"),
        ("site:open.spotify.com/playlist unsigned artist playlist", "Unsigned Artist"),
        ("site:open.spotify.com/playlist curator playlist email rap", "Curator Rap"),
        ("site:open.spotify.com/playlist curator playlist email hip hop", "Curator HH"),
        ("site:open.spotify.com/playlist curator playlist email lofi", "Curator Lo-Fi"),
        ("site:open.spotify.com/playlist playlist submission email contact", "Submission Email"),
        ("site:open.spotify.com/playlist send beats playlist", "Send Beats"),
        ("site:open.spotify.com/playlist promote your music playlist", "Promote Music"),
        ("site:open.spotify.com/playlist new artist rap playlist", "New Artist Rap"),
        ("site:open.spotify.com/playlist fresh finds submit", "Fresh Finds"),
        ("site:open.spotify.com/playlist undiscovered artists playlist", "Undiscovered"),
        ("site:open.spotify.com/playlist small artist playlist", "Small Artist"),
    ]
    for q, label in extras:
        ql = q.lower()
        if ql not in seen:
            seen.add(ql)
            queries.append((q, label))

    return queries


class TokenManager:
    """Manages anonymous Spotify tokens for the wg endpoint."""

    def __init__(self):
        self.token = None
        self.session = requests.Session()
        self.session.verify = False

    def get_token(self):
        if self.token:
            return self.token
        return self.refresh()

    def refresh(self):
        pid = random.choice(TOKEN_PLAYLISTS)
        self.session.headers["User-Agent"] = random.choice(USER_AGENTS)
        try:
            resp = self.session.get(
                f"https://open.spotify.com/embed/playlist/{pid}", timeout=15)
            tokens = re.findall(r'"accessToken":"([^"]+)"', resp.text)
            if tokens:
                self.token = tokens[0]
                return self.token
        except Exception:
            pass
        return None


def extract_contacts(text):
    if not text:
        return [], []
    emails = EMAIL_REGEX.findall(text)
    emails = [e for e in emails if e.lower() not in EMAIL_BLACKLIST
              and not e.endswith((".png", ".jpg", ".svg", ".gif", ".css", ".js"))]
    raw_ig = INSTAGRAM_REGEX.findall(text)
    instagrams = [h for h in raw_ig if h.lower() not in IG_STOPWORDS and len(h) > 2]
    return list(set(emails)), list(set(instagrams))


def get_playlist_data(session, token_mgr, playlist_id):
    """Fetch playlist description via internal wg endpoint (not rate limited)."""
    token = token_mgr.get_token()
    if not token:
        return None

    try:
        resp = session.get(
            f"https://spclient.wg.spotify.com/playlist/v2/playlist/{playlist_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        if resp.status_code == 401:
            token_mgr.refresh()
            token = token_mgr.get_token()
            if not token:
                return None
            resp = session.get(
                f"https://spclient.wg.spotify.com/playlist/v2/playlist/{playlist_id}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )

        if resp.status_code != 200:
            return None

        # Decode protobuf as text
        text = resp.content.decode("utf-8", errors="ignore")

        # Extract readable strings
        strings = re.findall(r"[\x20-\x7E]{3,}", text)

        # First long string is usually the name, second is description
        name = ""
        description = ""
        for s in strings:
            if len(s) >= 3 and not name:
                name = s.strip()
                continue
            if len(s) >= 10 and not description:
                description = s.strip()
                break

        # Extract contacts from full text content
        emails, instagrams = extract_contacts(text)

        # Check for editorial markers
        is_editorial = False
        text_lower = text.lower()
        for marker in ["spotify:user:spotify", "isalgotorial", '"true"']:
            if marker in text_lower:
                is_editorial = True
                break

        return {
            "name": name,
            "description": description,
            "emails": emails,
            "instagrams": instagrams,
            "editorial": is_editorial,
        }
    except Exception:
        return None


def ddg_search(query, max_results=30):
    """Search DuckDuckGo and extract Spotify playlist IDs."""
    playlist_ids = []
    try:
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=max_results)
            for r in results:
                url = r.get("href", "") or r.get("link", "")
                body = r.get("body", "") or r.get("snippet", "")
                for text in [url, body]:
                    for m in re.finditer(r"open\.spotify\.com/playlist/([a-zA-Z0-9]{22})", text):
                        playlist_ids.append(m.group(1))
    except Exception as e:
        err_str = str(e)
        if "Ratelimit" in err_str or "403" in err_str:
            print(f"    DDG rate limited, waiting 30s...")
            time.sleep(30)
        else:
            print(f"    DDG error: {e}")
            time.sleep(5)

    return list(dict.fromkeys(playlist_ids))


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
    filename = os.path.join(runs_dir, f"genre_run_{timestamp}.csv")
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(new_rows)
    return filename


def main():
    queries = build_search_queries()
    random.shuffle(queries)

    target_total = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 1500

    existing_rows, seen_contacts, seen_ids = load_existing()
    print(f"Loaded {len(existing_rows)} existing entries ({len(seen_contacts)} unique contacts)")
    print(f"Loaded {len(seen_ids)} known playlist IDs to skip")
    print(f"Target: {target_total} total | {len(queries)} search queries\n")

    session = requests.Session()
    session.verify = False
    session.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "*/*",
    })

    token_mgr = TokenManager()
    print("Getting initial token...")
    if not token_mgr.get_token():
        print("ERROR: Could not get token")
        return
    print("Token acquired!\n")

    all_rows = list(existing_rows)
    new_rows = []
    total_new = 0
    consecutive_ddg_errors = 0
    total_scraped = 0

    for i, (query, genre_label) in enumerate(queries):
        if len(all_rows) >= target_total:
            print(f"\nReached target of {target_total}+ total contacts!")
            break

        print(f"\n[{i+1}/{len(queries)}] '{query}' (total: {len(all_rows)}, +{total_new} this run)")

        playlist_ids = ddg_search(query, max_results=30)
        print(f"  Found {len(playlist_ids)} playlists from DDG")

        if not playlist_ids:
            consecutive_ddg_errors += 1
            if consecutive_ddg_errors >= 3:
                print("  DDG throttled. Pausing 45s...")
                time.sleep(45)
                consecutive_ddg_errors = 0
            continue
        consecutive_ddg_errors = 0

        new_for_query = 0
        for pid in playlist_ids:
            if pid in seen_ids:
                continue
            seen_ids.add(pid)

            data = get_playlist_data(session, token_mgr, pid)
            total_scraped += 1
            if not data:
                continue

            # Skip editorial
            if data["editorial"]:
                continue

            emails = data["emails"]
            instagrams = data["instagrams"]
            if not emails and not instagrams:
                continue

            email_str = ", ".join(emails)
            ig_str = ", ".join(instagrams)
            contact_key = (email_str or ig_str).lower()
            if contact_key in seen_contacts:
                continue
            seen_contacts.add(contact_key)

            row = {
                "email": email_str,
                "instagram": ig_str,
                "playlist_name": data["name"],
                "playlist_url": f"https://open.spotify.com/playlist/{pid}",
                "keyword": genre_label,
                "description_snippet": data["description"][:100].replace("\n", " ") if data["description"] else "",
                "followers": "",
                "priority": "",
            }
            all_rows.append(row)
            new_rows.append(row)
            new_for_query += 1
            total_new += 1
            print(f"    HIT: {data['name']} | {email_str or ig_str}")

            time.sleep(random.uniform(0.3, 0.8))

        count = save_csv(all_rows)
        print(f"  => +{new_for_query} new | {count} total ({total_new} this run, {total_scraped} scraped)")

        # Refresh token every 20 queries
        if i % 20 == 19:
            token_mgr.refresh()

        # Pace DDG searches
        time.sleep(random.uniform(6, 12))

    count = save_csv(all_rows)
    run_file = save_run_csv(new_rows)
    print(f"\n{'=' * 60}")
    print(f"DONE! +{total_new} new contacts this run. {count} total in output.csv")
    print(f"Total playlists scraped via wg endpoint: {total_scraped}")
    if run_file:
        print(f"New contacts saved to {run_file}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
