"""Spotify playlist curator scraper via Google search + page scraping.

Uses googlesearch-python library for reliable Google searches,
then scrapes contact info from Spotify playlist pages.
"""

import csv
import html as html_mod
import re
import sys
import time
import random

import requests
import urllib3
from googlesearch import search as gsearch

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
}
EMAIL_BLACKLIST = {
    "abuse@spotify.com", "support@spotify.com", "copyright@spotify.com",
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
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

        # Search full page for emails and instagrams
        emails = EMAIL_REGEX.findall(page_text)
        emails = [e for e in emails if e.lower() not in EMAIL_BLACKLIST
                  and not e.endswith((".png", ".jpg", ".svg", ".gif", ".css", ".js"))]

        raw_ig = INSTAGRAM_REGEX.findall(page_text)
        instagrams = [h for h in raw_ig if h.lower() not in IG_STOPWORDS]

        # Get description snippet from embedded JSON
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
            "emails": list(set(emails)),
            "instagrams": list(set(instagrams)),
            "description": description,
        }
    except Exception as e:
        return None


def find_playlists_google(keyword, num_results=30):
    """Use googlesearch-python to find Spotify playlists."""
    query = f'site:open.spotify.com/playlist {keyword}'
    playlist_ids = []

    try:
        results = gsearch(query, num_results=num_results, sleep_interval=5)
        for url in results:
            match = re.search(r"open\.spotify\.com/playlist/([a-zA-Z0-9]{22})", url)
            if match:
                playlist_ids.append(match.group(1))
    except Exception as e:
        print(f"    Google search error: {e}")
        time.sleep(30)

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
                    seen_contacts.add(email)
                if ig:
                    seen_contacts.add(ig)
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


def main():
    default_keywords = [
        # User-specified genres with submit focus
        "submit study beats", "submit jazzhop", "submit jazz hop",
        "submit chillhop", "submit chill hop",
        "submit hip hop", "submit conscious hip hop",
        "submit rap", "submit pop rap",
        "submit neo soul", "submit neo-soul",
        "submit bedroom pop", "submit lo-fi pop", "submit lofi pop",
        "submit alternative R&B", "submit indie R&B",
        "submit Latin hip hop", "submit boom bap",
        # Genre + playlist + submit
        "study beats playlist submit", "jazz hop playlist submit",
        "chill hop playlist submit", "hip hop playlist submit",
        "conscious hip hop playlist", "rap playlist submit",
        "pop rap playlist submit", "neo soul playlist submit",
        "bedroom pop playlist submit", "lofi playlist submit",
        "alternative R&B playlist", "indie R&B playlist submit",
        "Latin hip hop playlist", "boom bap playlist submit",
        # Email-focused queries
        "spotify playlist submit email rap",
        "spotify playlist submit email hip hop",
        "spotify playlist submit email R&B",
        "spotify playlist submit email lofi",
        "spotify playlist curators email",
        "hip hop playlist curators contact",
        "rap playlist curators contact email",
        "R&B playlist curators email",
        "lofi playlist curators email",
        # More broad searches
        "spotify submit your song playlist",
        "spotify accepting submissions playlist",
        "underground hip hop submit playlist",
        "independent artist playlist submit",
        "new artist rap playlist submit",
        "indie rap playlist submit",
        "chill rap playlist submit",
        "alternative hip hop submit",
        "afrobeats playlist submit",
        "latin rap playlist submit",
        "soul playlist submit",
        "jazz rap playlist submit",
        "conscious rap playlist submit",
    ]

    keywords = sys.argv[1:] if len(sys.argv) > 1 else default_keywords

    existing_rows, seen_contacts, seen_ids = load_existing()
    print(f"Loaded {len(existing_rows)} existing entries ({len(seen_contacts)} unique contacts)")
    print(f"Target: 2000-5000 contacts\n")

    session = make_session()
    all_rows = list(existing_rows)
    new_total = 0

    for i, keyword in enumerate(keywords):
        print(f"\n[{i+1}/{len(keywords)}] Searching: {keyword}")

        playlist_ids = find_playlists_google(keyword, num_results=50)
        print(f"  Found {len(playlist_ids)} playlists")

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
            contact_key = email_str if email_str else ig_str
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
            new_for_keyword += 1
            print(f"    NEW: {data['name']} | {email_str or ig_str}")

            time.sleep(random.uniform(1, 2))

        new_total += new_for_keyword
        count = save_csv(all_rows)
        print(f"  => +{new_for_keyword} new | {count} total in output.csv ({new_total} added this run)")

        # Check if we've hit our target
        if count >= 5000:
            print(f"\n  Reached target of 5000+ contacts!")
            break

        time.sleep(random.uniform(5, 10))

    print(f"\nDONE! Added {new_total} new contacts. Total: {len(all_rows)} in output.csv")


if __name__ == "__main__":
    main()
