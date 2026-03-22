# Spotify Email/Instagram Scraper

Scrapes email addresses and Instagram handles from Spotify playlist descriptions by searching for playlists matching genre keywords.

## How it works

- Gets an anonymous access token from Spotify's web player (no API key needed)
- Uses that token to query the standard Spotify API
- Searches playlists by genre keywords
- Extracts emails and Instagram handles from playlist descriptions using regex
- Saves results to CSV

## Setup

1. Install dependencies: `pip install -r requirements.txt`
2. Run: `python src/scraper.py <keyword1> [keyword2] ...`

No API credentials needed — the scraper obtains anonymous tokens automatically.

## Key rules

- Always paginate Spotify search results (10 per page, up to 1000 offset)
- Always fetch full playlist details for complete descriptions (search results truncate them)
- Use regex: `r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'`
- Add 0.15s delay between API calls for rate limiting
- Handle 429 responses with exponential backoff
- Auto-refresh token on 401 (expired)
- Tag every result with the keyword that found it
- CSV columns: email, instagram, playlist_name, playlist_url, keyword, description_snippet

## Project Structure

- `src/scraper.py` — Main scraper logic
- `requirements.txt` — Python dependencies
