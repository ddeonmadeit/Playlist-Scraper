"""Spotify playlist curator scraper via DuckDuckGo search + direct page scraping.

Bypasses Spotify API entirely — uses DuckDuckGo to find playlist URLs,
then scrapes contact info from the actual Spotify playlist pages.
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
from duckduckgo_search import DDGS

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

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
]


def make_session():
    s = requests.Session()
    s.verify = False
    s.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return s


def extract_contacts_from_text(text):
    """Extract emails and instagrams from text."""
    if not text:
        return [], []
    emails = EMAIL_REGEX.findall(text)
    emails = [e for e in emails if e.lower() not in EMAIL_BLACKLIST
              and not e.endswith((".png", ".jpg", ".svg", ".gif", ".css", ".js"))]
    raw_ig = INSTAGRAM_REGEX.findall(text)
    instagrams = [h for h in raw_ig if h.lower() not in IG_STOPWORDS and len(h) > 2]
    return list(set(emails)), list(set(instagrams))


def scrape_playlist_page(session, playlist_id):
    """Scrape contact info from a Spotify playlist page."""
    url = f"https://open.spotify.com/playlist/{playlist_id}"
    try:
        session.headers["User-Agent"] = random.choice(USER_AGENTS)
        resp = session.get(url, timeout=20)
        if resp.status_code != 200:
            return None

        page_text = resp.text

        # Get playlist name
        name_match = re.search(r'property="og:title"\s+content="([^"]*)"', page_text)
        name = html_mod.unescape(name_match.group(1)) if name_match else ""

        # Extract contacts from full page
        emails, instagrams = extract_contacts_from_text(page_text)

        # Get description snippet
        desc_matches = re.findall(r'"description"\s*:\s*"((?:[^"\\]|\\.){10,})"', page_text)
        description = ""
        if desc_matches:
            for d in sorted(desc_matches, key=len, reverse=True):
                try:
                    decoded = d.encode().decode("unicode_escape", errors="ignore")
                except Exception:
                    decoded = d
                if any(c.isalpha() for c in decoded):
                    description = decoded
                    break

        return {
            "name": name,
            "emails": emails,
            "instagrams": instagrams,
            "description": description,
        }
    except Exception:
        return None


def ddg_find_playlists(keyword, max_results=40):
    """Use DuckDuckGo to find Spotify playlist URLs."""
    query = f"site:open.spotify.com/playlist {keyword}"
    playlist_ids = []

    try:
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=max_results)
            for r in results:
                url = r.get("href", "") or r.get("link", "")
                match = re.search(r"open\.spotify\.com/playlist/([a-zA-Z0-9]{22})", url)
                if match:
                    playlist_ids.append(match.group(1))
                # Also check body text for playlist links
                body = r.get("body", "") or r.get("snippet", "")
                for m in re.finditer(r"open\.spotify\.com/playlist/([a-zA-Z0-9]{22})", body):
                    playlist_ids.append(m.group(1))
    except Exception as e:
        print(f"    DDG error: {e}")
        time.sleep(15)

    return list(dict.fromkeys(playlist_ids))


def ddg_find_playlists_with_contacts(keyword, max_results=60):
    """Search DuckDuckGo for playlists that mention email/submission in snippets."""
    queries = [
        f"site:open.spotify.com/playlist {keyword}",
        f"site:open.spotify.com/playlist {keyword} email",
        f"site:open.spotify.com/playlist {keyword} submit",
    ]
    playlist_ids = []

    for query in queries:
        try:
            with DDGS() as ddgs:
                results = ddgs.text(query, max_results=max_results // len(queries))
                for r in results:
                    url = r.get("href", "") or r.get("link", "")
                    match = re.search(r"open\.spotify\.com/playlist/([a-zA-Z0-9]{22})", url)
                    if match:
                        playlist_ids.append(match.group(1))
        except Exception as e:
            print(f"    DDG error: {e}")
            time.sleep(10)

        time.sleep(random.uniform(3, 6))

    return list(dict.fromkeys(playlist_ids))


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
        # Core submit keywords
        "submit rap playlist", "submit hip hop playlist",
        "submit lofi playlist", "submit R&B playlist",
        "submit beats playlist", "submit neo soul playlist",
        "submit boom bap playlist", "submit jazz hop playlist",
        "submit chill playlist", "submit study beats playlist",
        "submit bedroom pop playlist", "submit conscious rap playlist",
        "submit alternative hip hop", "submit indie hip hop",
        "submit soul playlist", "submit afrobeats playlist",
        "submit trap playlist", "submit drill playlist",
        "submit phonk playlist", "submit cloud rap playlist",
        "submit emo rap playlist", "submit UK rap playlist",
        "submit reggaeton playlist", "submit dancehall playlist",
        # Underground / indie
        "underground rap playlist", "underground hip hop playlist",
        "underground R&B playlist", "underground lofi playlist",
        "underground music playlist", "underground artist playlist",
        "hidden gems playlist", "hidden gems hip hop",
        "hidden gems rap playlist", "hidden gems indie",
        "undiscovered artists playlist", "unsigned artist playlist",
        "independent artist playlist", "independent rapper playlist",
        "up and coming artist playlist", "emerging artist playlist",
        "new artist playlist", "fresh finds playlist",
        "small artist playlist", "DIY music playlist",
        # Email/contact focused
        "spotify playlist submit email rap",
        "spotify playlist submit email hip hop",
        "spotify playlist curators email",
        "rap playlist curators contact email",
        "hip hop playlist curators contact",
        "R&B playlist curators email",
        "lofi playlist curators email",
        "playlist submission email contact",
        "playlist submission rap", "playlist submission hip hop",
        "playlist submission R&B", "playlist submission lofi",
        # Genre searches
        "rap playlist accepting submissions",
        "hip hop playlist accepting submissions",
        "lofi playlist accepting submissions",
        "R&B playlist accepting submissions",
        "indie playlist accepting submissions",
        "pop playlist accepting submissions",
        "rock playlist accepting submissions",
        "electronic playlist accepting submissions",
        # Regional
        "UK hip hop playlist submit", "Canadian hip hop playlist",
        "Australian hip hop playlist", "French rap playlist",
        "German hip hop playlist", "Atlanta rap playlist",
        "NYC rap playlist", "LA rap playlist",
        "Chicago rap playlist", "Detroit rap playlist",
        "Southern rap playlist", "West coast hip hop playlist",
        "East coast rap playlist", "Midwest rap playlist",
        # Electronic / dance
        "submit EDM playlist", "submit house playlist",
        "submit techno playlist", "submit deep house playlist",
        "submit future bass playlist", "submit dubstep playlist",
        "submit DnB playlist", "submit synthwave playlist",
        "submit ambient playlist", "submit chillwave playlist",
        # Pop / mainstream
        "submit pop playlist", "submit indie pop playlist",
        "submit K-pop playlist", "submit Latin pop playlist",
        # Rock / alternative
        "submit indie rock playlist", "submit alternative playlist",
        "submit dream pop playlist", "submit shoegaze playlist",
        "submit punk rock playlist", "submit metal playlist",
        # More patterns
        "send beats to playlist curators",
        "promote your music playlist submit",
        "jazz playlist submit email",
        "blues playlist submit",
        "gospel playlist submit",
        "funk playlist submit",
        "reggae playlist submit",
        "afrobeats playlist curators",
        "Latin playlist submit",
        "country playlist submit",
        "folk playlist submit",
        # More underground
        "SoundCloud rap playlist",
        "backpack rap playlist",
        "experimental hip hop playlist",
        "lo-fi indie playlist",
        "underground electronic playlist",
        "underground bass music playlist",
        "underground punk playlist",
        "underground metal playlist",
        "underground folk playlist",
        # Broad
        "spotify playlist email submissions",
        "curator playlist contact email",
        "spotify playlist accepting music",
        "spotify playlist open submissions",
        "music blog playlist submit",
        "playlist pitching email",
        "free playlist submission spotify",
        "indie music playlist curators",
        "hip hop music blog playlist",
        "rap blog playlist submit",
    ]

    target_total = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 1500

    existing_rows, seen_contacts, seen_ids = load_existing()
    print(f"Loaded {len(existing_rows)} existing entries ({len(seen_contacts)} unique contacts)")
    print(f"Target: {target_total} total in output.csv\n")

    session = make_session()
    all_rows = list(existing_rows)
    new_rows_this_run = []
    total_new = 0
    consecutive_errors = 0

    for i, keyword in enumerate(keywords):
        current_total = len(all_rows)
        if current_total >= target_total:
            print(f"\nReached target of {target_total}+ contacts!")
            break

        print(f"\n[{i+1}/{len(keywords)}] '{keyword}' (total: {current_total}, new: {total_new})")

        playlist_ids = ddg_find_playlists(keyword, max_results=50)
        print(f"  Found {len(playlist_ids)} playlists from DDG")

        if not playlist_ids:
            consecutive_errors += 1
            if consecutive_errors >= 5:
                print("  Too many empty results. Pausing 60s...")
                time.sleep(60)
                consecutive_errors = 0
            continue
        consecutive_errors = 0

        new_for_keyword = 0
        for pid in playlist_ids:
            if pid in seen_ids:
                continue
            seen_ids.add(pid)

            data = scrape_playlist_page(session, pid)
            if not data:
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

            playlist_url = f"https://open.spotify.com/playlist/{pid}"
            snippet = data["description"][:100].replace("\n", " ") if data["description"] else ""
            row = {
                "email": email_str,
                "instagram": ig_str,
                "playlist_name": data["name"],
                "playlist_url": playlist_url,
                "keyword": keyword,
                "description_snippet": snippet,
            }
            all_rows.append(row)
            new_rows_this_run.append(row)
            new_for_keyword += 1
            total_new += 1
            print(f"    HIT: {data['name']} | {email_str or ig_str}")

            time.sleep(random.uniform(1, 2))

        count = save_csv(all_rows)
        print(f"  => +{new_for_keyword} new | {count} total ({total_new} new this run)")

        # Pace DDG searches
        time.sleep(random.uniform(5, 10))

    count = save_csv(all_rows)
    run_file = save_new_contacts_csv(new_rows_this_run)
    print(f"\n{'=' * 60}")
    print(f"DONE! +{total_new} new contacts this run. {count} total in output.csv")
    if run_file:
        print(f"New contacts saved to {run_file}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
