import csv
import re
import sys
import time
import urllib3

import requests
from tqdm import tqdm

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
INSTAGRAM_REGEX = re.compile(r"(?:instagram|ig|insta)[:\s/@]*@?([a-zA-Z0-9_.]{1,30})", re.IGNORECASE)

MAX_SEARCH_OFFSET = 1000
SEARCH_LIMIT = 10
REQUEST_DELAY = 0.3

# Known Spotify editorial playlists used to fetch anonymous tokens from embed pages
TOKEN_PLAYLISTS = [
    "37i9dQZF1DXcBWIGoYBM5M",  # Today's Top Hits
    "37i9dQZF1DX0XUsuxWHRQd",  # RapCaviar
    "37i9dQZF1DWXRqgorJj26U",  # Rock Classics
    "37i9dQZF1DX4sWSpwq3LiO",  # Peaceful Piano
]


def get_anonymous_token():
    """Get an anonymous Spotify access token by scraping an embed page.

    No API credentials needed — the embed page includes a short-lived
    access token that works with the standard Spotify Web API.
    """
    session = requests.Session()
    session.verify = False
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    })

    for playlist_id in TOKEN_PLAYLISTS:
        url = f"https://open.spotify.com/embed/playlist/{playlist_id}"
        try:
            resp = session.get(url, timeout=15)
            resp.raise_for_status()
            tokens = re.findall(r'"accessToken":"([^"]+)"', resp.text)
            if tokens:
                return tokens[0]
        except requests.RequestException:
            continue

    raise RuntimeError(
        "Failed to get anonymous Spotify token from any embed page. "
        "Spotify may be blocking requests from this IP."
    )


def api_request(token, url, params=None):
    """Make a Spotify API request with rate-limit handling and retries."""
    headers = {"Authorization": f"Bearer {token}"}
    max_retries = 5

    for attempt in range(max_retries):
        resp = requests.get(url, headers=headers, params=params, timeout=15, verify=False)

        if resp.status_code == 200:
            time.sleep(REQUEST_DELAY)
            return resp.json()
        elif resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 2 ** attempt))
            # Cap the wait at 60s per retry to avoid extremely long waits
            retry_after = min(retry_after, 60)
            print(f"  Rate limited. Retrying in {retry_after}s...")
            time.sleep(retry_after)
        elif resp.status_code == 400:
            return None
        elif resp.status_code == 401:
            raise RuntimeError("TOKEN_EXPIRED")
        else:
            resp.raise_for_status()

    raise RuntimeError(f"API call failed after {max_retries} retries (rate limited)")


def search_playlists(token, keyword):
    """Search for playlists by keyword, paginating up to the 1000 offset limit."""
    playlists = []
    offset = 0
    url = "https://api.spotify.com/v1/search"

    with tqdm(desc=f"Searching '{keyword}'", unit="playlist") as pbar:
        while offset < MAX_SEARCH_OFFSET:
            params = {
                "q": keyword,
                "type": "playlist",
                "limit": SEARCH_LIMIT,
                "offset": offset,
            }
            results = api_request(token, url, params)
            if not results:
                break

            items = results.get("playlists", {}).get("items", [])
            if not items:
                break

            playlists.extend(items)
            pbar.update(len(items))
            offset += SEARCH_LIMIT

    return playlists


def get_full_playlist(token, playlist_id):
    """Fetch full playlist details (search results truncate descriptions)."""
    url = f"https://api.spotify.com/v1/playlists/{playlist_id}"
    params = {"fields": "id,name,description,external_urls"}
    return api_request(token, url, params)


def extract_emails(text):
    """Extract email addresses from text using regex."""
    if not text:
        return []
    return EMAIL_REGEX.findall(text)


def extract_instagrams(text):
    """Extract Instagram handles from text using regex."""
    if not text:
        return []
    return INSTAGRAM_REGEX.findall(text)


def scrape_keyword(token, keyword, seen_playlist_ids):
    """Search playlists for a keyword and extract emails/instagrams from descriptions.

    Returns (token, results) — token may be refreshed if it expired mid-run.
    """
    try:
        playlists = search_playlists(token, keyword)
    except RuntimeError as e:
        if "TOKEN_EXPIRED" in str(e):
            print("  Token expired, refreshing...")
            token = get_anonymous_token()
            playlists = search_playlists(token, keyword)
        else:
            raise

    results = []

    for playlist in tqdm(playlists, desc=f"Fetching details for '{keyword}'", unit="playlist"):
        if not playlist or not playlist.get("id"):
            continue

        playlist_id = playlist["id"]
        if playlist_id in seen_playlist_ids:
            continue
        seen_playlist_ids.add(playlist_id)

        try:
            full = get_full_playlist(token, playlist_id)
        except RuntimeError as e:
            if "TOKEN_EXPIRED" in str(e):
                print("  Token expired, refreshing...")
                token = get_anonymous_token()
                full = get_full_playlist(token, playlist_id)
            else:
                raise

        if not full:
            continue
        description = full.get("description", "") or ""
        emails = extract_emails(description)
        instagrams = extract_instagrams(description)

        if not emails and not instagrams:
            continue

        snippet = description[:100].replace("\n", " ")
        playlist_url = full.get("external_urls", {}).get("spotify", "")
        instagram_str = ", ".join(instagrams) if instagrams else ""
        email_str = ", ".join(emails) if emails else ""

        results.append({
            "email": email_str,
            "instagram": instagram_str,
            "playlist_name": full.get("name", ""),
            "playlist_url": playlist_url,
            "keyword": keyword,
            "description_snippet": snippet,
        })

    return token, results


def save_to_csv(rows, filename="output.csv"):
    """Save results to CSV, deduplicating by playlist URL."""
    seen = set()
    unique_rows = []
    for row in rows:
        key = row["playlist_url"]
        if key not in seen:
            seen.add(key)
            unique_rows.append(row)

    fieldnames = ["email", "instagram", "playlist_name", "playlist_url", "keyword", "description_snippet"]
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(unique_rows)

    return len(unique_rows)


def main():
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <keyword1> [keyword2] ...")
        return

    keywords = sys.argv[1:]

    print("Getting anonymous Spotify token (no API key needed)...")
    try:
        token = get_anonymous_token()
        print("Token acquired!\n")
    except Exception as e:
        print(f"Error getting token: {e}")
        return

    all_results = []
    seen_playlist_ids = set()
    for keyword in keywords:
        print(f"\nProcessing keyword: {keyword}")
        token, results = scrape_keyword(token, keyword, seen_playlist_ids)
        all_results.extend(results)
        print(f"  Found {len(results)} playlist(s) with contact info for '{keyword}'")

    if all_results:
        count = save_to_csv(all_results)
        print(f"\nSaved {count} unique playlist(s) to output.csv")
    else:
        print("\nNo playlists with email/instagram found across any keywords.")


if __name__ == "__main__":
    main()
