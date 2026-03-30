"""Round 6 scraper - PLAYLIST-ONLY contacts.

Every contact MUST have a real Spotify playlist name + URL.
Approach: find playlist IDs from curator directories, search results,
and Telegram channels, then check each playlist's Spotify data for
contact info (email/IG) in the description. Skip any without both.
"""

import csv
import re
import sys
import time
import random
from urllib.parse import urlparse

import requests
import urllib3
from ddgs import DDGS

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
IG_REGEX = re.compile(
    r"(?:instagram\.com/|(?:^|[\s|•·\-,])(?:ig|insta(?:gram)?)[:\s/@]+@?)([a-zA-Z0-9][a-zA-Z0-9_.]{2,29})",
    re.IGNORECASE | re.MULTILINE,
)
IG_STOP = {
    "for","the","and","this","that","with","from","not","are","was",
    "but","has","had","have","will","can","all","her","his","its",
    "our","you","com","org","net","www","http","https",
    "reel","reels","explore","stories","p",
}
JUNK_DOMAINS = {
    "spotify.com","submithub.com","example.com","w3.org","schema.org",
    "googleapis.com","google.com","facebook.com","twitter.com","youtube.com",
    "apple.com","sentry.io","blogger.com","wordpress.com","wordpress.org",
    "gravatar.com","cloudflare.com","yandex.ru","mail.ru","wixpress.com",
    "playlistpush.com","wp.com","cdn.com","microsoft.com","amazon.com",
}
JUNK_EMAILS = {
    "example@gmail.com","email@example.com","your@email.com",
    "youremail@gmail.com","name@email.com","test@test.com",
    "noreply@spotify.com","info@submithub.com","noreply@blogger.com",
    "example@domain.com","john@doe.com",
}

TOKEN_PLS = [
    "37i9dQZF1DXcBWIGoYBM5M","37i9dQZF1DX0XUsuxWHRQd",
    "37i9dQZF1DWXRqgorJj26U","37i9dQZF1DX4SBhb3fZpCo",
]
UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]
FN = ["email","instagram","playlist_name","playlist_url","keyword",
      "description_snippet","followers","priority"]


def valid_email(e):
    el = e.lower().strip()
    if el in JUNK_EMAILS:
        return False
    domain = el.split("@")[-1] if "@" in el else ""
    if domain in JUNK_DOMAINS or any(domain.endswith(f".{j}") for j in JUNK_DOMAINS):
        return False
    if len(e) < 6:
        return False
    if e.endswith((".png",".jpg",".svg",".gif",".css",".js",".ico",".webp")):
        return False
    tld = domain.split(".")[-1] if "." in domain else ""
    if len(tld) < 2 or len(tld) > 10:
        return False
    local = el.split("@")[0]
    if len(local) > 20 and all(c in "0123456789abcdef-" for c in local):
        return False
    if "example" in el or "your@" in el or "u002f" in el or "u003e" in el:
        return False
    return True


def valid_playlist_name(name):
    """Check that the playlist name looks real (not garbled binary)."""
    if not name or len(name) < 2:
        return False
    # Count printable ASCII letters/digits
    printable = sum(1 for c in name if c.isalnum() or c in " -_&!.,'()/:+")
    # At least 40% should be normal chars
    if printable / len(name) < 0.4:
        return False
    return True


class TokenManager:
    def __init__(self):
        self.token = None
        self.session = requests.Session()
        self.session.verify = False

    def get_token(self):
        return self.token or self.refresh()

    def refresh(self):
        for pid in TOKEN_PLS:
            self.session.headers["User-Agent"] = random.choice(UAS)
            try:
                resp = self.session.get(
                    f"https://open.spotify.com/embed/playlist/{pid}", timeout=15)
                tokens = re.findall(r'"accessToken":"([^"]+)"', resp.text)
                if tokens:
                    self.token = tokens[0]
                    return self.token
            except Exception:
                continue
        return None


def get_playlist_data(session, token_mgr, playlist_id):
    """Get playlist info from Spotify. Returns None if unusable."""
    token = token_mgr.get_token()
    if not token:
        return None
    try:
        resp = session.get(
            f"https://spclient.wg.spotify.com/playlist/v2/playlist/{playlist_id}",
            headers={"Authorization": f"Bearer {token}"}, timeout=15)
        if resp.status_code == 401:
            token_mgr.refresh()
            token = token_mgr.get_token()
            if not token:
                return None
            resp = session.get(
                f"https://spclient.wg.spotify.com/playlist/v2/playlist/{playlist_id}",
                headers={"Authorization": f"Bearer {token}"}, timeout=15)
        if resp.status_code != 200:
            return None

        text = resp.content.decode("utf-8", errors="ignore")

        # Skip editorial playlists
        if "spotify:user:spotify" in text.lower() or "isalgotorial" in text.lower():
            return None

        # Extract name + description from printable strings
        strings = re.findall(r"[\x20-\x7E]{3,}", text)
        name, desc = "", ""
        for s in strings:
            if len(s) >= 3 and not name:
                name = s.strip()
                continue
            if len(s) >= 10 and not desc:
                desc = s.strip()
                break

        # Extract contacts
        emails = [e for e in EMAIL_REGEX.findall(text) if valid_email(e)]
        raw_ig = IG_REGEX.findall(text)
        igs = [h for h in raw_ig if h.lower() not in IG_STOP and len(h) > 2]

        # MUST have contact info
        if not emails and not igs:
            return None

        # MUST have a valid-looking playlist name
        if not valid_playlist_name(name):
            return None

        return {
            "name": name,
            "description": desc,
            "emails": list(set(emails)),
            "instagrams": list(set(igs)),
        }
    except Exception:
        return None


def scrape_playlist_ids(url, session):
    """Scrape a web page for Spotify playlist IDs."""
    try:
        resp = session.get(url, timeout=20, headers={
            "User-Agent": random.choice(UAS), "Accept": "text/html,*/*",
        }, allow_redirects=True)
        if resp.status_code != 200 or len(resp.text) < 100:
            return []
        return list(dict.fromkeys(re.findall(
            r"open\.spotify\.com/playlist/([a-zA-Z0-9]{22})", resp.text)))
    except Exception:
        return []


def load_existing(filename="output.csv"):
    rows, seen_contacts, seen_ids = [], set(), set()
    try:
        with open(filename, "r", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                for k in ("followers","priority"):
                    if k not in row:
                        row[k] = ""
                rows.append(row)
                url = row.get("playlist_url","")
                if "/playlist/" in url:
                    seen_ids.add(url.split("/playlist/")[-1].split("?")[0])
                for e in row.get("email","").split(","):
                    if e.strip():
                        seen_contacts.add(e.strip().lower())
                for i in row.get("instagram","").split(","):
                    if i.strip():
                        seen_contacts.add(i.strip().lower())
    except FileNotFoundError:
        pass
    return rows, seen_contacts, seen_ids


def save_csv(rows, filename="output.csv"):
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FN)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def try_add(all_rows, seen_contacts, seen_ids, pid, data, keyword):
    """Try to add a playlist contact. Returns True if added."""
    email_str = ", ".join(data["emails"][:3])
    ig_str = ", ".join(data["instagrams"][:3])
    key = (email_str or ig_str).lower()
    if key in seen_contacts:
        return False
    seen_contacts.add(key)
    for e in data["emails"]:
        seen_contacts.add(e.lower())
    all_rows.append({
        "email": email_str,
        "instagram": ig_str,
        "playlist_name": data["name"],
        "playlist_url": f"https://open.spotify.com/playlist/{pid}",
        "keyword": keyword[:50],
        "description_snippet": data["description"][:100].replace("\n"," ") if data["description"] else "",
        "followers": "",
        "priority": "high",
    })
    return True


def main():
    target = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 200

    existing_rows, seen_contacts, seen_ids = load_existing()
    print(f"Loaded {len(existing_rows)} existing | {len(seen_ids)} known playlist IDs")
    print(f"Target: +{target} NEW contacts (all with playlist name + URL)\n")

    session = requests.Session()
    session.verify = False
    token_mgr = TokenManager()
    if not token_mgr.get_token():
        print("ERROR: No token")
        return
    print("Token ready.\n")

    all_rows = list(existing_rows)
    total_new = 0

    # ══════════════════════════════════════════════════════
    # PHASE 1: Mass playlist scrape from curator directories
    # ══════════════════════════════════════════════════════
    print("=== PHASE 1: Curator directory playlist scrape ===\n")

    directory_urls = [
        # PlaylistLookup - all genre subpages
        *[f"https://www.playlistlookup.com/genre/{g}" for g in [
            "hip-hop","r-and-b","pop","indie","electronic","rock","soul",
            "jazz","folk","country","metal","punk","reggae","latin",
            "classical","ambient","blues","gospel","world","dancehall",
            "afrobeats","house","techno","drum-and-bass","dubstep",
            "trance","garage","disco","funk","new-wave",
        ]],
        # Soundplate genre pages
        *[f"https://play.soundplate.com/{g}" for g in [
            "hiphop","rnb","pop","indie","electronic","rock","soul",
            "jazz","folk","country","metal","reggae","latin","alt",
            "blues","funk","punk","dancehall","afrobeats","lofi",
            "kpop","jpop","trap","drill","grime","garage",
            "house","techno","dnb","dubstep","trance","ambient",
            "chillout","workout","party","sleep","study","focus",
            "cooking","gaming","roadtrip","summer","winter",
        ]],
        # IndieMono genre submission pages
        *[f"https://indiemono.com/submit-music-{g}-playlists/" for g in [
            "rap","rnb","pop","indie","electronic","rock","soul",
            "jazz","folk","country","metal","reggae","latin",
            "ambient","funk","punk","dancehall","afrobeats","lo-fi",
            "hip-hop","alternative","blues","gospel","classical",
        ]],
        # Telegram playlist channels - deep pagination
        *[f"https://t.me/s/spotifypls?before={n}" for n in range(100, 7500, 150)],
        # Curator club categories
        *[f"https://curatorclub.com/genre/{g}" for g in [
            "hip-hop","rnb","pop","indie","electronic","rock",
        ]],
        # ShareToPros genre pages
        *[f"https://www.sharetopros.com/genre/{g}" for g in [
            "hip-hop","r&b","pop","indie","electronic","rock","soul",
        ]],
    ]

    # Shuffle to avoid hitting same site repeatedly
    random.shuffle(directory_urls)

    checked_count = 0
    for url in directory_urls:
        if total_new >= target:
            break

        pids = scrape_playlist_ids(url, session)
        new_pids = [p for p in pids if p not in seen_ids]

        if not new_pids:
            time.sleep(random.uniform(1, 2))
            continue

        hits = 0
        for pid in new_pids:
            if total_new >= target:
                break
            seen_ids.add(pid)
            checked_count += 1
            data = get_playlist_data(session, token_mgr, pid)
            if not data:
                continue

            if try_add(all_rows, seen_contacts, seen_ids, pid, data,
                      urlparse(url).netloc):
                total_new += 1
                hits += 1
                print(f"  [{total_new}/{target}] {data['name'][:40]} | "
                      f"{', '.join(data['emails'][:2]) or ', '.join(data['instagrams'][:2])}")
            time.sleep(random.uniform(0.15, 0.4))

        if hits > 0 and total_new % 10 < hits:
            save_csv(all_rows)

        time.sleep(random.uniform(1.5, 3))

    save_csv(all_rows)
    print(f"\nPhase 1 done: +{total_new} new, checked {checked_count} playlists\n")

    # ══════════════════════════════════════════════════════
    # PHASE 2: DDG search for pages with playlist links
    # ══════════════════════════════════════════════════════
    if total_new < target:
        print(f"=== PHASE 2: DDG search (need {target - total_new} more) ===\n")

        search_queries = [
            # Queries designed to find pages with embedded playlist links
            "open.spotify.com/playlist submit email rap",
            "open.spotify.com/playlist submit email hip hop",
            "open.spotify.com/playlist submit email R&B",
            "open.spotify.com/playlist submit email lofi",
            "open.spotify.com/playlist submit email pop",
            "open.spotify.com/playlist submit email indie",
            "open.spotify.com/playlist submit email soul",
            "open.spotify.com/playlist submit email trap",
            "open.spotify.com/playlist curator email",
            "open.spotify.com/playlist curator contact",
            "spotify playlist curators list open.spotify.com",
            "best spotify playlists submit open.spotify.com",
            "independent spotify playlists open.spotify.com email",

            # Blog articles with embedded playlists
            "top spotify playlists independent artists submit 2025",
            "top spotify playlists independent artists submit 2026",
            "best spotify playlists submit free music 2026",
            "spotify playlist curators accepting music 2026 list",
            "biggest independent spotify playlists 2026",
            "spotify playlist curators free submission 2026",

            # Submission guides with playlist links
            "how to submit music spotify playlist free guide",
            "submit your song spotify playlist list free",
            "spotify curators free submit hip hop rap R&B 2026",
            "best curated spotify playlists accepting submissions 2026",
            "spotify playlist submission contacts free 2026",

            # Linktree / bio pages with playlists
            "site:linktr.ee open.spotify.com/playlist submit",
            "site:linktr.ee spotify playlist curator rap",
            "site:linktr.ee spotify playlist curator R&B",
            "site:linktr.ee spotify playlist curator lofi",
            "site:linktr.ee spotify playlist curator hip hop",

            # iMusician, artist.tools with playlist links
            "site:imusician.pro spotify playlist submit",
            "site:artist.tools submit hip-hop 2026",
            "site:artist.tools submit r-and-b",
            "site:artist.tools submit pop",
            "site:artist.tools submit electronic",
            "site:artist.tools submit rock",
            "site:artist.tools submit lofi",
            "site:artist.tools submit soul",
            "site:artist.tools submit jazz",
            "site:artist.tools submit folk",

            # RhythmRidge, OmariMC type blogs
            "site:rhythmridge.com spotify playlists",
            "site:omarimc.com spotify playlists submit",
            "site:djwillgill.com spotify playlist curators",
            "site:twostorymelody.com spotify playlists",
        ]

        scraped_urls = set()

        for qi, query in enumerate(search_queries):
            if total_new >= target:
                break
            print(f"[{qi+1}/{len(search_queries)}] {query[:55]}... (new: {total_new}/{target})")

            try:
                with DDGS() as ddgs:
                    results = ddgs.text(query, max_results=15)
            except Exception as e:
                if "Ratelimit" in str(e):
                    print("  Rate limited, waiting 60s...")
                    time.sleep(60)
                    continue
                time.sleep(5)
                continue

            for r in results:
                if total_new >= target:
                    break
                url = r.get("href","") or r.get("link","")
                if not url or url in scraped_urls:
                    continue
                scraped_urls.add(url)

                pids = scrape_playlist_ids(url, session)
                new_pids = [p for p in pids if p not in seen_ids]
                if not new_pids:
                    continue

                print(f"  {url[:60]}... ({len(new_pids)} new playlists)")

                for pid in new_pids[:25]:
                    if total_new >= target:
                        break
                    seen_ids.add(pid)
                    checked_count += 1
                    data = get_playlist_data(session, token_mgr, pid)
                    if not data:
                        continue
                    if try_add(all_rows, seen_contacts, seen_ids, pid, data, query):
                        total_new += 1
                        print(f"    [{total_new}/{target}] {data['name'][:40]} | "
                              f"{', '.join(data['emails'][:2]) or ', '.join(data['instagrams'][:2])}")
                    time.sleep(random.uniform(0.15, 0.4))

                if total_new > 0 and total_new % 15 == 0:
                    save_csv(all_rows)

            time.sleep(random.uniform(8, 15))

    # Final save
    count = save_csv(all_rows)
    print(f"\n{'='*60}")
    print(f"DONE! +{total_new} new playlist contacts. {count} total in output.csv")
    print(f"Checked {checked_count} playlists total")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
