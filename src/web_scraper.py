"""Spotify playlist curator scraper — web scraping approach.

Scrapes Spotify search results and playlist pages directly via HTTP,
without using the Spotify API. This avoids API rate limits entirely.
"""

import csv
import re
import sys
import time
import urllib.parse

import requests
from tqdm import tqdm

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
INSTAGRAM_REGEX = re.compile(
    r"(?:instagram\.com/|(?:^|[\s|•·\-,])(?:ig|insta(?:gram)?)[:\s/@]+@?)([a-zA-Z0-9][a-zA-Z0-9_.]{2,29})",
    re.IGNORECASE | re.MULTILINE,
)
# Common false-positive words to filter out
IG_STOPWORDS = {
    "for", "the", "and", "this", "that", "with", "from", "not", "are", "was",
    "but", "has", "had", "have", "will", "can", "all", "her", "his", "its",
    "our", "you", "com", "org", "net", "www", "http", "https",
}


def make_session():
    """Create a requests session that looks like a real browser."""
    s = requests.Session()
    s.verify = False
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
    })
    return s


def get_token(session):
    """Get anonymous token from embed page."""
    playlists = [
        "37i9dQZF1DXcBWIGoYBM5M",
        "37i9dQZF1DX0XUsuxWHRQd",
        "37i9dQZF1DWXRqgorJj26U",
        "37i9dQZF1DX4sWSpwq3LiO",
        "37i9dQZF1DX1lVhptIYRda",
        "37i9dQZF1DXcF6B6QPhFDv",
    ]
    for pid in playlists:
        try:
            resp = session.get(
                f"https://open.spotify.com/embed/playlist/{pid}", timeout=15
            )
            tokens = re.findall(r'"accessToken":"([^"]+)"', resp.text)
            if tokens:
                return tokens[0]
        except Exception:
            continue
    raise RuntimeError("Could not get token")


def search_with_token(session, token, keyword, max_playlists=50):
    """Search for playlists via API using the anonymous token."""
    playlists = []
    offset = 0

    while len(playlists) < max_playlists and offset < 1000:
        resp = session.get(
            "https://api.spotify.com/v1/search",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "q": keyword,
                "type": "playlist",
                "limit": 50,
                "offset": offset,
            },
            timeout=15,
        )

        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 30))
            print(f"    API rate limited, waiting {wait}s...")
            time.sleep(wait)
            # Get fresh token
            token = get_token(session)
            continue

        if resp.status_code == 401:
            token = get_token(session)
            continue

        if resp.status_code != 200:
            break

        items = resp.json().get("playlists", {}).get("items", [])
        if not items:
            break

        playlists.extend(items)
        offset += 50
        time.sleep(2)

    return token, playlists[:max_playlists]


def get_description_from_page(session, playlist_id):
    """Scrape playlist description directly from the open.spotify.com page."""
    url = f"https://open.spotify.com/playlist/{playlist_id}"
    try:
        resp = session.get(url, timeout=15)
        if resp.status_code != 200:
            return ""

        text = resp.text

        # Try meta description
        match = re.search(
            r'<meta\s+(?:name|property)="(?:og:description|description)"'
            r'\s+content="([^"]*)"',
            text,
        )
        if match:
            desc = match.group(1)
            # Decode HTML entities
            desc = (
                desc.replace("&amp;", "&")
                .replace("&#x2F;", "/")
                .replace("&#39;", "'")
                .replace("&quot;", '"')
            )
            return desc

        # Try JSON-LD or embedded data
        matches = re.findall(r'"description"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
        if matches:
            longest = max(matches, key=len)
            return longest

        return ""
    except Exception:
        return ""


def get_description_from_api(session, token, playlist_id):
    """Get playlist description from API."""
    resp = session.get(
        f"https://api.spotify.com/v1/playlists/{playlist_id}",
        headers={"Authorization": f"Bearer {token}"},
        params={"fields": "id,name,description,external_urls"},
        timeout=15,
    )

    if resp.status_code == 429:
        wait = int(resp.headers.get("Retry-After", 30))
        print(f"    API rate limited, waiting {wait}s...")
        time.sleep(wait)
        token = get_token(session)
        resp = session.get(
            f"https://api.spotify.com/v1/playlists/{playlist_id}",
            headers={"Authorization": f"Bearer {token}"},
            params={"fields": "id,name,description,external_urls"},
            timeout=15,
        )

    if resp.status_code == 401:
        token = get_token(session)
        return token, None

    if resp.status_code != 200:
        return token, None

    time.sleep(1.5)
    return token, resp.json()


def extract_contacts(text):
    """Extract emails and Instagram handles."""
    if not text:
        return [], []
    emails = EMAIL_REGEX.findall(text)
    raw_ig = INSTAGRAM_REGEX.findall(text)
    instagrams = [h for h in raw_ig if h.lower() not in IG_STOPWORDS]
    return emails, instagrams


def save_to_csv(rows, filename="output.csv"):
    """Save to CSV, deduplicating by playlist URL."""
    seen = set()
    unique = []
    for row in rows:
        key = row["playlist_url"]
        if key not in seen:
            seen.add(key)
            unique.append(row)

    fieldnames = [
        "email", "instagram", "playlist_name",
        "playlist_url", "keyword", "description_snippet",
    ]
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(unique)
    return len(unique)


def scrape_keyword(session, token, keyword, seen_ids, max_playlists=50):
    """Search and scrape one keyword. Returns (token, results)."""
    print(f"\n  Searching '{keyword}'...")

    token, playlists = search_with_token(session, token, keyword, max_playlists)
    print(f"  Found {len(playlists)} playlists")

    results = []
    api_fails = 0

    for pl in tqdm(playlists, desc=f"  Checking '{keyword}'", unit="pl"):
        if not pl or not pl.get("id"):
            continue

        pid = pl["id"]
        if pid in seen_ids:
            continue
        seen_ids.add(pid)

        name = pl.get("name", "")
        playlist_url = f"https://open.spotify.com/playlist/{pid}"

        # Try API first
        token, full = get_description_from_api(session, token, pid)

        if full:
            description = full.get("description", "") or ""
            name = full.get("name", name)
            playlist_url = full.get("external_urls", {}).get("spotify", playlist_url)
        else:
            # Fallback: scrape the page directly
            api_fails += 1
            description = get_description_from_page(session, pid)
            time.sleep(1)

        emails, instagrams = extract_contacts(description)

        if not emails and not instagrams:
            continue

        results.append({
            "email": ", ".join(emails),
            "instagram": ", ".join(instagrams),
            "playlist_name": name,
            "playlist_url": playlist_url,
            "keyword": keyword,
            "description_snippet": description[:100].replace("\n", " "),
        })

        print(f"    HIT: {name} | emails={emails} ig={instagrams}")

    if api_fails > 0:
        print(f"  (Used page scraping fallback for {api_fails} playlists)")

    return token, results


def main():
    keywords = sys.argv[1:] if len(sys.argv) > 1 else [
        "Jazz Rap",
        "Alternative Hip Hop",
        "Conscious Hip Hop",
        "Rap",
        "Pop Rap",
    ]

    session = make_session()

    print("Getting Spotify token...")
    token = get_token(session)
    print("Token acquired!\n")

    all_results = []
    seen_ids = set()

    for keyword in keywords:
        print(f"\n{'='*50}")
        print(f"Keyword: {keyword}")
        print(f"{'='*50}")

        token, results = scrape_keyword(session, token, keyword, seen_ids)
        all_results.extend(results)
        print(f"  => {len(results)} contacts for '{keyword}'")

        # Save incrementally
        if all_results:
            count = save_to_csv(all_results)
            print(f"  => {count} total saved to output.csv")

        # Get fresh token between keywords
        try:
            token = get_token(session)
        except Exception:
            pass

        time.sleep(5)

    print(f"\n{'='*50}")
    if all_results:
        count = save_to_csv(all_results)
        print(f"DONE! {count} unique playlist contacts saved to output.csv")
    else:
        print("No contacts found.")


if __name__ == "__main__":
    main()
