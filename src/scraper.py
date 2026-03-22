import os
import re

import spotipy
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyClientCredentials
from tqdm import tqdm

load_dotenv()

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")


def get_spotify_client():
    """Authenticate and return a Spotify client."""
    auth_manager = SpotifyClientCredentials(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
    )
    return spotipy.Spotify(auth_manager=auth_manager)


def get_playlist_tracks(sp, playlist_url):
    """Fetch all tracks from a Spotify playlist."""
    playlist_id = playlist_url.split("/")[-1].split("?")[0]
    results = sp.playlist_tracks(playlist_id)
    tracks = results["items"]

    while results["next"]:
        results = sp.next(results)
        tracks.extend(results["items"])

    return tracks


def extract_artist_ids(tracks):
    """Extract unique artist IDs from a list of tracks."""
    artist_ids = set()
    for track in tracks:
        if track["track"]:
            for artist in track["track"]["artists"]:
                artist_ids.add(artist["id"])
    return list(artist_ids)


def scrape_emails_from_bio(bio):
    """Extract email addresses from an artist bio string."""
    if not bio:
        return []
    email_pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    return re.findall(email_pattern, bio)


def get_artist_emails(sp, artist_ids):
    """Look up each artist and attempt to find emails in their bio/about."""
    results = []

    for artist_id in tqdm(artist_ids, desc="Scanning artists"):
        artist = sp.artist(artist_id)
        name = artist["name"]

        # Spotify API doesn't expose bios directly — this is a placeholder
        # for where you'd integrate additional data sources (e.g. web scraping
        # the artist's page or using a third-party bio API).
        bio = ""

        emails = scrape_emails_from_bio(bio)
        if emails:
            results.append({"artist": name, "emails": emails})

    return results


def main():
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        print("Error: Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in .env")
        return

    playlist_url = input("Enter Spotify playlist URL: ").strip()
    if not playlist_url:
        print("No URL provided.")
        return

    sp = get_spotify_client()

    print("Fetching playlist tracks...")
    tracks = get_playlist_tracks(sp, playlist_url)
    print(f"Found {len(tracks)} tracks.")

    artist_ids = extract_artist_ids(tracks)
    print(f"Found {len(artist_ids)} unique artists.")

    artist_emails = get_artist_emails(sp, artist_ids)

    if artist_emails:
        print(f"\nFound emails for {len(artist_emails)} artist(s):")
        for entry in artist_emails:
            print(f"  {entry['artist']}: {', '.join(entry['emails'])}")
    else:
        print("\nNo emails found.")


if __name__ == "__main__":
    main()
