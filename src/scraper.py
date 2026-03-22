import csv
import os
import re
import sys
import time

import spotipy
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyClientCredentials
from tqdm import tqdm

load_dotenv()

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

MAX_SEARCH_OFFSET = 1000
SEARCH_LIMIT = 50
API_DELAY = 0.1


def get_spotify_client():
    """Authenticate and return a Spotify client using client_credentials flow."""
    auth_manager = SpotifyClientCredentials(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
    )
    return spotipy.Spotify(auth_manager=auth_manager)


def api_call_with_backoff(func, *args, **kwargs):
    """Execute a Spotify API call with rate-limit handling and delay."""
    max_retries = 5
    for attempt in range(max_retries):
        try:
            result = func(*args, **kwargs)
            time.sleep(API_DELAY)
            return result
        except spotipy.exceptions.SpotifyException as e:
            if e.http_status == 429:
                retry_after = int(e.headers.get("Retry-After", 2 ** attempt))
                print(f"  Rate limited. Retrying in {retry_after}s...")
                time.sleep(retry_after)
            else:
                raise
    raise RuntimeError(f"API call failed after {max_retries} retries")


def search_playlists(sp, keyword):
    """Search for playlists by keyword, paginating up to the 1000 offset limit."""
    playlists = []
    offset = 0

    with tqdm(desc=f"Searching '{keyword}'", unit="playlist") as pbar:
        while offset < MAX_SEARCH_OFFSET:
            results = api_call_with_backoff(
                sp.search,
                q=keyword,
                type="playlist",
                limit=SEARCH_LIMIT,
                offset=offset,
            )
            items = results["playlists"]["items"]
            if not items:
                break

            playlists.extend(items)
            pbar.update(len(items))
            offset += SEARCH_LIMIT

    return playlists


def get_full_playlist(sp, playlist_id):
    """Fetch full playlist details (search results truncate descriptions)."""
    return api_call_with_backoff(sp.playlist, playlist_id, fields="id,name,description,external_urls")


def extract_emails(text):
    """Extract email addresses from text using regex."""
    if not text:
        return []
    return EMAIL_REGEX.findall(text)


def scrape_keyword(sp, keyword):
    """Search playlists for a keyword and extract emails from full descriptions."""
    playlists = search_playlists(sp, keyword)
    results = []

    for playlist in tqdm(playlists, desc=f"Fetching details for '{keyword}'", unit="playlist"):
        if not playlist or not playlist.get("id"):
            continue

        full = get_full_playlist(sp, playlist["id"])
        description = full.get("description", "") or ""
        emails = extract_emails(description)

        if not emails:
            continue

        snippet = description[:100].replace("\n", " ")
        playlist_url = full.get("external_urls", {}).get("spotify", "")

        for email in emails:
            results.append({
                "email": email,
                "playlist_name": full.get("name", ""),
                "playlist_url": playlist_url,
                "keyword": keyword,
                "description_snippet": snippet,
            })

    return results


def save_to_csv(rows, filename="output.csv"):
    """Save results to CSV, deduplicating by email address."""
    seen = set()
    unique_rows = []
    for row in rows:
        if row["email"] not in seen:
            seen.add(row["email"])
            unique_rows.append(row)

    fieldnames = ["email", "playlist_name", "playlist_url", "keyword", "description_snippet"]
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(unique_rows)

    return len(unique_rows)


def main():
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        print("Error: Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in .env")
        return

    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <keyword1> [keyword2] ...")
        return

    keywords = sys.argv[1:]
    sp = get_spotify_client()

    all_results = []
    for keyword in keywords:
        print(f"\nProcessing keyword: {keyword}")
        results = scrape_keyword(sp, keyword)
        all_results.extend(results)
        print(f"  Found {len(results)} email(s) for '{keyword}'")

    if all_results:
        count = save_to_csv(all_results)
        print(f"\nSaved {count} unique email(s) to output.csv")
    else:
        print("\nNo emails found across any keywords.")


if __name__ == "__main__":
    main()
