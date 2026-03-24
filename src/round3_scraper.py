"""Round 3 scraper - fresh DDG queries + directory scraping to reach 1500 contacts.

Uses completely different query patterns from rounds 1 & 2:
- Curator-focused queries (playlist curator names, blogs)
- Submission platform pages (SubmitHub, Playlist Push, Daily Playlists, etc.)
- Genre-specific niche terms not covered before
- Broader music discovery terms
- Direct directory page scraping for curator emails
"""

import csv
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
    "privacy@spotify.com", "legal@spotify.com", "info@spotify.com",
    "example@gmail.com", "email@example.com", "your@email.com",
    "youremail@gmail.com", "name@email.com",
}

TOKEN_PLAYLISTS = [
    "37i9dQZF1DXcBWIGoYBM5M", "37i9dQZF1DX0XUsuxWHRQd",
    "37i9dQZF1DWXRqgorJj26U", "37i9dQZF1DX4sWSpwq3LiO",
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

FIELDNAMES = ["email", "instagram", "playlist_name", "playlist_url", "keyword",
              "description_snippet", "followers", "priority"]

# ── Completely new query patterns ──────────────────────────────────────

def build_queries():
    queries = []
    seen = set()

    def add(q, label):
        ql = q.lower().strip()
        if ql not in seen:
            seen.add(ql)
            queries.append((q, label))

    # ── Pattern 1: Niche subgenres not used in rounds 1-2 ──
    niche_genres = [
        "phonk", "cloud rap", "emo rap", "drill", "UK drill", "afrobeats",
        "amapiano", "dancehall", "grime", "UK rap", "trip hop", "downtempo",
        "chillwave", "vaporwave", "future bass", "future funk", "synth soul",
        "experimental hip hop", "abstract hip hop", "backpacker rap",
        "instrumental hip hop", "lo-fi jazz", "jazz fusion", "smooth R&B",
        "90s R&B", "2000s R&B", "classic soul", "funk", "G-funk",
        "trap soul", "PBR&B", "indie soul", "dark trap", "melodic rap",
        "pluggnb", "rage beats", "detroit type beats", "UK garage",
        "broken beat", "acid jazz", "electro soul", "tropical house",
        "reggae hip hop", "dub", "spoken word", "poetry rap",
        "anime lo-fi", "gaming beats", "coding music", "work from home beats",
        "meditation beats", "sleep beats", "ambient hip hop",
        "ethereal R&B", "witch house", "shoegaze pop", "dream pop",
        "city pop", "K-R&B", "J-hip hop", "French rap",
        "German rap", "Brazilian hip hop", "Portuguese rap",
    ]
    for genre in niche_genres:
        add(f"site:open.spotify.com/playlist {genre} playlist", genre)
        add(f"site:open.spotify.com/playlist {genre} submit music", f"{genre} submit")

    # ── Pattern 2: Curator-focused ──
    curator_terms = [
        "playlist curator contact", "spotify curator email",
        "independent playlist curator", "playlist curators accepting submissions",
        "submit music to playlist curator", "spotify playlist submission email",
        "playlist submission contact info", "curator playlist gmail",
        "playlist contact @gmail", "spotify curator @yahoo",
        "playlist owner email address", "reach out playlist curator",
        "playlist submission form spotify", "free playlist submission spotify",
        "submit song spotify playlist free", "playlist pitching email",
        "spotify playlist placement free", "playlist promotion submit",
        "how to submit to spotify playlists email",
        "spotify playlist curators list 2024", "spotify playlist curators list 2025",
    ]
    for term in curator_terms:
        add(f"site:open.spotify.com/playlist {term}", "Curator Search")

    # ── Pattern 3: Mood/activity playlists (high follower, often have emails) ──
    mood_terms = [
        "workout hip hop", "gym rap", "running beats", "party rap",
        "road trip hip hop", "summer vibes hip hop", "night drive beats",
        "smoke session playlist", "vibes playlist chill", "mood playlist",
        "late night R&B", "rainy day lo-fi", "morning coffee beats",
        "weekend vibes playlist", "house party playlist",
        "pre-game playlist rap", "BBQ playlist hip hop",
        "driving music hip hop", "shower playlist", "cooking beats",
        "cleaning playlist hip hop", "workout motivation rap",
        "chill smoke playlist", "late night drive playlist",
    ]
    for term in mood_terms:
        add(f"site:open.spotify.com/playlist {term}", term.title())

    # ── Pattern 4: Year-specific playlists ──
    for year in ["2023", "2024", "2025"]:
        for genre in ["hip hop", "rap", "R&B", "lo-fi", "neo soul", "indie"]:
            add(f"site:open.spotify.com/playlist best {genre} {year}", f"{genre} {year}")
            add(f"site:open.spotify.com/playlist new {genre} {year} submit", f"New {genre} {year}")

    # ── Pattern 5: Playlist naming patterns curators use ──
    naming_patterns = [
        "hidden gems", "underground vibes", "slept on", "up next",
        "on repeat", "fresh picks", "new music friday indie",
        "rising artists", "ones to watch", "next up", "on the come up",
        "undiscovered", "unsigned", "emerging artists",
        "independent artists", "bedroom artists", "home studio",
        "SoundCloud to Spotify", "new wave", "the wave",
        "vibes only", "no skips", "certified bangers", "heat check",
        "fire playlist", "flame playlist", "straight heat",
        "chill selection", "smooth selection", "vibe check",
    ]
    for pattern in naming_patterns:
        add(f"site:open.spotify.com/playlist \"{pattern}\"", pattern.title())

    # ── Pattern 6: Email-in-description patterns ──
    email_patterns = [
        "@gmail.com submit spotify playlist",
        "@hotmail.com spotify playlist curator",
        "@yahoo.com spotify playlist submit",
        "@outlook.com spotify playlist music",
        "contact us spotify playlist curator email",
        "DM or email spotify playlist",
        "submissions open spotify playlist",
        "send your music spotify playlist",
        "accepting submissions spotify playlist",
    ]
    for ep in email_patterns:
        add(f"site:open.spotify.com/playlist {ep}", "Email Pattern")

    # ── Pattern 7: Blog/directory pages that list curator emails ──
    directory_queries = [
        "spotify playlist curators email list 2024",
        "spotify playlist submission contacts list",
        "best spotify playlists to submit to email",
        "independent spotify playlist curators contact",
        "free spotify playlist submission sites",
        "spotify playlist curators accepting submissions free",
        "list of spotify playlist curators with email",
        "spotify curator database free",
        "how to get on spotify playlists email contacts",
        "spotify playlist promotion free email list",
        "top spotify playlist curators hip hop email",
        "lofi spotify playlist curators email list",
        "R&B spotify playlist curators submit email",
        "rap spotify playlist curators free submission",
        "indie playlist curators spotify email",
        "submit to spotify playlists free no submithub",
    ]
    for dq in directory_queries:
        add(dq, "Directory")

    random.shuffle(queries)
    return queries


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
              and not e.endswith((".png", ".jpg", ".svg", ".gif", ".css", ".js"))
              and len(e) > 5 and "." in e.split("@")[-1]]
    raw_ig = INSTAGRAM_REGEX.findall(text)
    instagrams = [h for h in raw_ig if h.lower() not in IG_STOPWORDS and len(h) > 2]
    return list(set(emails)), list(set(instagrams))


def get_playlist_data(session, token_mgr, playlist_id):
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
        name = ""
        description = ""
        for s in strings:
            if len(s) >= 3 and not name:
                name = s.strip()
                continue
            if len(s) >= 10 and not description:
                description = s.strip()
                break

        emails, instagrams = extract_contacts(text)

        is_editorial = False
        text_lower = text.lower()
        for marker in ["spotify:user:spotify", "isalgotorial"]:
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


def get_oembed_name(playlist_id):
    """Get clean playlist name via oembed endpoint."""
    try:
        resp = requests.get(
            f"https://open.spotify.com/oembed?url=https://open.spotify.com/playlist/{playlist_id}",
            timeout=10)
        if resp.status_code == 200:
            return resp.json().get("title", "")
    except Exception:
        pass
    return ""


def ddg_search(query, max_results=40):
    playlist_ids = []
    try:
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=max_results)
            for r in results:
                url = r.get("href", "") or r.get("link", "")
                body = r.get("body", "") or r.get("snippet", "")
                title = r.get("title", "")
                for text in [url, body, title]:
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


def scrape_directory_page(url, session):
    """Scrape a web page for Spotify playlist URLs and emails."""
    results = []
    try:
        resp = session.get(url, timeout=20, headers={
            "User-Agent": random.choice(USER_AGENTS)
        })
        if resp.status_code != 200:
            return results
        text = resp.text

        # Find playlist IDs
        pids = re.findall(r"open\.spotify\.com/playlist/([a-zA-Z0-9]{22})", text)

        # Find emails in the page
        page_emails = EMAIL_REGEX.findall(text)
        page_emails = [e for e in page_emails if e.lower() not in EMAIL_BLACKLIST
                       and not e.endswith((".png", ".jpg", ".svg", ".gif", ".css", ".js"))]

        for pid in list(dict.fromkeys(pids)):
            results.append({"playlist_id": pid, "page_emails": list(set(page_emails))})

    except Exception as e:
        print(f"    Directory scrape error: {e}")
    return results


def ddg_find_directories():
    """Search DDG for curator directory pages."""
    directory_urls = []
    queries = [
        "spotify playlist curators email list",
        "free spotify playlist submission contacts",
        "spotify playlist curator database",
        "best spotify playlists submit music email contact",
        "indie music spotify playlist curators list",
        "hip hop spotify curator email list free",
    ]
    for q in queries:
        try:
            with DDGS() as ddgs:
                results = ddgs.text(q, max_results=10)
                for r in results:
                    url = r.get("href", "") or r.get("link", "")
                    if url and "spotify.com" not in url:
                        directory_urls.append(url)
        except Exception:
            time.sleep(10)
        time.sleep(random.uniform(5, 10))

    return list(dict.fromkeys(directory_urls))


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


def main():
    target_total = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 1500

    existing_rows, seen_contacts, seen_ids = load_existing()
    print(f"Loaded {len(existing_rows)} existing entries ({len(seen_contacts)} contacts, {len(seen_ids)} playlist IDs)")
    print(f"Target: {target_total} | Need: {max(0, target_total - len(existing_rows))} more\n")

    if len(existing_rows) >= target_total:
        print("Already at target!")
        return

    session = requests.Session()
    session.verify = False
    session.headers.update({"User-Agent": random.choice(USER_AGENTS), "Accept": "*/*"})

    token_mgr = TokenManager()
    print("Getting token...")
    if not token_mgr.get_token():
        print("ERROR: Could not get token")
        return
    print("Token acquired!\n")

    all_rows = list(existing_rows)
    new_rows = []
    total_new = 0

    # ── Phase 1: Scrape directory pages for playlist IDs + emails ──
    print("=" * 60)
    print("PHASE 1: Scraping curator directory pages...")
    print("=" * 60)

    directory_urls = ddg_find_directories()
    print(f"Found {len(directory_urls)} directory pages to scrape\n")

    for i, url in enumerate(directory_urls[:20]):
        if len(all_rows) >= target_total:
            break
        print(f"  [{i+1}] {url[:80]}...")
        entries = scrape_directory_page(url, session)
        dir_new = 0
        for entry in entries:
            pid = entry["playlist_id"]
            if pid in seen_ids:
                continue
            seen_ids.add(pid)

            data = get_playlist_data(session, token_mgr, pid)
            if not data or data["editorial"]:
                continue

            # Merge page emails with playlist emails
            all_emails = list(set(data["emails"] + entry["page_emails"]))
            all_emails = [e for e in all_emails if e.lower() not in EMAIL_BLACKLIST]
            instagrams = data["instagrams"]

            if not all_emails and not instagrams:
                continue

            email_str = ", ".join(all_emails[:3])
            ig_str = ", ".join(instagrams[:3])
            contact_key = (email_str or ig_str).lower()
            if contact_key in seen_contacts:
                continue
            seen_contacts.add(contact_key)

            name = get_oembed_name(pid) or data["name"]
            row = {
                "email": email_str,
                "instagram": ig_str,
                "playlist_name": name,
                "playlist_url": f"https://open.spotify.com/playlist/{pid}",
                "keyword": "Directory",
                "description_snippet": data["description"][:100].replace("\n", " ") if data["description"] else "",
                "followers": "",
                "priority": "",
            }
            all_rows.append(row)
            new_rows.append(row)
            dir_new += 1
            total_new += 1
            print(f"    HIT: {name} | {email_str or ig_str}")
            time.sleep(random.uniform(0.3, 0.8))

        if dir_new > 0:
            save_csv(all_rows)
            print(f"  => +{dir_new} from this page | {len(all_rows)} total")
        time.sleep(random.uniform(2, 5))

    print(f"\nPhase 1 done: +{total_new} contacts. Total: {len(all_rows)}\n")

    # ── Phase 2: DDG searches with fresh queries ──
    print("=" * 60)
    print("PHASE 2: DDG searches with fresh query patterns...")
    print("=" * 60)

    queries = build_queries()
    print(f"{len(queries)} fresh queries to run\n")

    consecutive_ddg_errors = 0
    phase2_new = 0

    for i, (query, genre_label) in enumerate(queries):
        if len(all_rows) >= target_total:
            print(f"\nReached target of {target_total}!")
            break

        print(f"\n[{i+1}/{len(queries)}] '{query[:70]}...' (total: {len(all_rows)}, +{total_new})")

        playlist_ids = ddg_search(query, max_results=40)
        new_pids = [p for p in playlist_ids if p not in seen_ids]
        print(f"  Found {len(playlist_ids)} playlists ({len(new_pids)} new)")

        if not playlist_ids:
            consecutive_ddg_errors += 1
            if consecutive_ddg_errors >= 3:
                print("  DDG throttled. Pausing 60s...")
                time.sleep(60)
                consecutive_ddg_errors = 0
            continue
        consecutive_ddg_errors = 0

        new_for_query = 0
        for pid in new_pids:
            seen_ids.add(pid)
            data = get_playlist_data(session, token_mgr, pid)
            if not data or data["editorial"]:
                continue

            if not data["emails"] and not data["instagrams"]:
                continue

            email_str = ", ".join(data["emails"][:3])
            ig_str = ", ".join(data["instagrams"][:3])
            contact_key = (email_str or ig_str).lower()
            if contact_key in seen_contacts:
                continue
            seen_contacts.add(contact_key)

            name = get_oembed_name(pid) or data["name"]
            row = {
                "email": email_str,
                "instagram": ig_str,
                "playlist_name": name,
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
            phase2_new += 1
            print(f"    HIT: {name} | {email_str or ig_str}")
            time.sleep(random.uniform(0.3, 0.8))

        if new_for_query > 0:
            save_csv(all_rows)
        print(f"  => +{new_for_query} new | {len(all_rows)} total")

        if i % 20 == 19:
            token_mgr.refresh()

        time.sleep(random.uniform(6, 12))

    count = save_csv(all_rows)
    print(f"\n{'=' * 60}")
    print(f"DONE! +{total_new} new contacts. {count} total in output.csv")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
