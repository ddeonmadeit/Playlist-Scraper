# Spotify Email Scraper

Scrapes email addresses from Spotify playlist descriptions by searching for playlists matching genre keywords.

## How it works

- Uses the Spotify API (client_credentials flow via spotipy)
- Searches playlists by genre keywords
- Extracts emails from playlist descriptions using regex
- Saves results to CSV

## Setup

1. Copy `.env.example` to `.env` and fill in your Spotify API credentials.
2. Install dependencies: `pip install -r requirements.txt`
3. Run: `python src/scraper.py <keyword1> [keyword2] ...`

## Key rules

- Always paginate Spotify search results (50 per page, up to 1000 offset)
- Always fetch full playlist details for complete descriptions (search results truncate them)
- Use regex: `r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'`
- Add 0.1s delay between API calls for rate limiting
- Handle 429 responses with exponential backoff
- Tag every email with the keyword that found it
- CSV columns: email, playlist_name, playlist_url, keyword, description_snippet

## Project Structure

- `src/scraper.py` — Main scraper logic
- `.env` — Spotify API credentials (not committed)
- `requirements.txt` — Python dependencies
