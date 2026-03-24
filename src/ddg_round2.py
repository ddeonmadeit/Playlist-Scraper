"""Round 2 DDG scraper — fresh queries not used in round 1.

Uses DuckDuckGo + Spotify wg endpoint to bypass API rate limits.
Generates new query patterns to find playlists not discovered before.
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
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
]


def build_round2_queries():
    """Fresh queries not used in round 1 — different patterns and phrasings."""
    queries = []

    # Pattern 1: "spotify playlist [genre] curator"
    genres = [
        "lofi", "hip hop", "rap", "R&B", "neo soul", "jazz", "chill",
        "boom bap", "soul", "pop", "indie", "alternative", "lo-fi beats",
        "study", "focus", "bedroom pop", "conscious rap", "latin rap",
        "trap", "drill", "jazz hop", "chillhop", "bedroom r&b",
    ]
    for g in genres:
        queries.append(f"spotify playlist {g} curator")
        queries.append(f"spotify {g} playlist curators contact")
        queries.append(f"spotify {g} playlist accepting music")
        queries.append(f"spotify {g} playlist send music to")

    # Pattern 2: "open.spotify.com playlist" + different keywords
    submit_words = [
        "submissions open", "submit your track", "send your music",
        "accepting demos", "demo submission", "music submission",
        "send tracks to", "email us your music", "looking for music",
        "open for submissions", "promote your music",
    ]
    for sw in submit_words:
        queries.append(f"site:open.spotify.com/playlist {sw}")

    # Pattern 3: Genre + curator/submission site patterns
    for g in genres:
        queries.append(f"{g} spotify playlist curator email 2024")
        queries.append(f"{g} spotify playlist curator email 2025")
        queries.append(f"{g} spotify playlist curator email 2026")

    # Pattern 4: Specific submission platforms/directories
    queries.extend([
        "spotify playlist submission free email",
        "spotify playlist pitching free curators",
        "independent spotify playlist curators list",
        "free spotify playlist submission curators email",
        "spotify playlist curators accepting submissions list",
        "spotify curators email list hip hop",
        "spotify curators email list lofi",
        "spotify curators email list R&B",
        "spotify curators email list pop",
        "spotify curators email list rap",
        "spotify playlist submission contacts",
        "how to submit to spotify playlists email",
        "best spotify playlist curators email",
    ])

    # Pattern 5: More site:spotify queries with different angles
    additional_spotify = [
        "site:open.spotify.com/playlist email gmail.com",
        "site:open.spotify.com/playlist email hotmail.com",
        "site:open.spotify.com/playlist email outlook.com",
        "site:open.spotify.com/playlist email protonmail",
        "site:open.spotify.com/playlist email yahoo",
        "site:open.spotify.com/playlist instagram submit",
        "site:open.spotify.com/playlist @gmail.com hip hop",
        "site:open.spotify.com/playlist @gmail.com lofi",
        "site:open.spotify.com/playlist @gmail.com rap",
        "site:open.spotify.com/playlist @gmail.com R&B",
        "site:open.spotify.com/playlist @gmail.com soul",
        "site:open.spotify.com/playlist @gmail.com pop",
        "site:open.spotify.com/playlist @gmail.com indie",
        "site:open.spotify.com/playlist @gmail.com jazz",
        "site:open.spotify.com/playlist @gmail.com chill",
        "site:open.spotify.com/playlist @gmail.com beats",
        "site:open.spotify.com/playlist curator contact hip hop",
        "site:open.spotify.com/playlist curator contact lofi",
        "site:open.spotify.com/playlist curator contact rap",
        "site:open.spotify.com/playlist curator contact soul",
        "site:open.spotify.com/playlist DM for submissions",
        "site:open.spotify.com/playlist send your music",
        "site:open.spotify.com/playlist accepting tracks",
        "site:open.spotify.com/playlist open for submissions",
        "site:open.spotify.com/playlist demo submissions",
        "site:open.spotify.com/playlist indie hip hop email",
        "site:open.spotify.com/playlist underground rap email",
        "site:open.spotify.com/playlist chill beats email",
        "site:open.spotify.com/playlist jazzhop email",
        "site:open.spotify.com/playlist neo soul email",
        "site:open.spotify.com/playlist boom bap email",
        "site:open.spotify.com/playlist trap email",
        "site:open.spotify.com/playlist lo-fi email",
        "site:open.spotify.com/playlist study email",
        "site:open.spotify.com/playlist bedroom email",
        "site:open.spotify.com/playlist dark r&b email",
        "site:open.spotify.com/playlist indie r&b email",
        "site:open.spotify.com/playlist alternative soul email",
        "site:open.spotify.com/playlist latin email",
        "site:open.spotify.com/playlist conscious rap email",
        "site:open.spotify.com/playlist pop rap email",
    ]
    queries.extend(additional_spotify)

    # Deduplicate
    seen = set()
    unique = []
    for q in queries:
        ql = q.lower()
        if ql not in seen:
            seen.add(ql)
            unique.append(q)

    random.shuffle(unique)
    return unique


class TokenManager:
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
            resp = self.session.get(f"https://open.spotify.com/embed/playlist/{pid}", timeout=15)
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
    """Fetch playlist description via internal wg endpoint."""
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

        text = resp.content.decode("utf-8", errors="ignore")
        strings = re.findall(r"[\x20-\x7E]{3,}", text)
        name = strings[0].strip() if strings else ""
        emails, instagrams = extract_contacts(text)

        # Check editorial
        is_editorial = "spotify:user:spotify" in text.lower() or "isalgotorial" in text.lower()

        return {
            "name": name,
            "emails": emails,
            "instagrams": instagrams,
            "editorial": is_editorial,
        }
    except Exception:
        return None


def get_playlist_name_oembed(session, playlist_id):
    """Get clean playlist name from oembed endpoint."""
    try:
        resp = session.get(
            f"https://open.spotify.com/oembed?url=https://open.spotify.com/playlist/{playlist_id}",
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json().get("title", "")
    except Exception:
        pass
    return ""


def ddg_search(query, max_results=30):
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
            print(f"    DDG rate limited, waiting 45s...")
            time.sleep(45)
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
    filename = os.path.join(runs_dir, f"ddg_round2_{timestamp}.csv")
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(new_rows)
    return filename


def main():
    queries = build_round2_queries()
    target_total = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 1500

    existing_rows, seen_contacts, seen_ids = load_existing()
    print(f"Loaded {len(existing_rows)} existing entries ({len(seen_contacts)} unique contacts)")
    print(f"Loaded {len(seen_ids)} known playlist IDs to skip")
    print(f"Target: {target_total} total | {len(queries)} fresh queries\n")

    session = requests.Session()
    session.verify = False
    session.headers.update({"User-Agent": random.choice(USER_AGENTS), "Accept": "*/*"})

    token_mgr = TokenManager()
    print("Getting token...")
    if not token_mgr.get_token():
        print("ERROR: No token")
        return
    print("Token acquired!\n")

    all_rows = list(existing_rows)
    new_rows = []
    total_new = 0
    consecutive_ddg_errors = 0

    for i, query in enumerate(queries):
        if len(all_rows) >= target_total:
            print(f"\nReached target of {target_total}+ total!")
            break

        print(f"\n[{i+1}/{len(queries)}] '{query}' (total: {len(all_rows)}, +{total_new} this run)")

        pids = ddg_search(query, max_results=30)
        print(f"  Found {len(pids)} playlists")

        if not pids:
            consecutive_ddg_errors += 1
            if consecutive_ddg_errors >= 3:
                print("  DDG throttled. Pausing 45s...")
                time.sleep(45)
                consecutive_ddg_errors = 0
            continue
        consecutive_ddg_errors = 0

        new_for_query = 0
        for pid in pids:
            if pid in seen_ids:
                continue
            seen_ids.add(pid)

            data = get_playlist_data(session, token_mgr, pid)
            if not data or data["editorial"]:
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

            # Get clean name from oembed
            name = get_playlist_name_oembed(session, pid) or data["name"]

            row = {
                "email": email_str,
                "instagram": ig_str,
                "playlist_name": name,
                "playlist_url": f"https://open.spotify.com/playlist/{pid}",
                "keyword": query[:50],
                "description_snippet": "",
                "followers": "",
                "priority": "",
            }
            all_rows.append(row)
            new_rows.append(row)
            new_for_query += 1
            total_new += 1
            print(f"    HIT: {name} | {email_str or ig_str}")

            time.sleep(random.uniform(0.3, 0.8))

        count = save_csv(all_rows)
        print(f"  => +{new_for_query} new | {count} total ({total_new} this run)")

        if i % 20 == 19:
            token_mgr.refresh()

        time.sleep(random.uniform(6, 12))

    count = save_csv(all_rows)
    run_file = save_run_csv(new_rows)
    print(f"\n{'=' * 60}")
    print(f"DONE! +{total_new} new contacts this run. {count} total in output.csv")
    if run_file:
        print(f"New contacts saved to {run_file}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
