"""Spotify playlist curator scraper using web search + page scraping.

This module is meant to be called from the main orchestrator which
uses the WebSearch tool to find playlists, then this scrapes the pages.
"""

import csv
import html as html_mod
import re
import random

import requests
import urllib3

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


def scrape_playlist_page(playlist_id):
    """Scrape contact info from a Spotify playlist page."""
    s = requests.Session()
    s.verify = False
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html",
    })

    url = f"https://open.spotify.com/playlist/{playlist_id}"
    try:
        resp = s.get(url, timeout=20)
        if resp.status_code != 200:
            return None

        page_text = resp.text

        name_match = re.search(r'property="og:title"\s+content="([^"]*)"', page_text)
        name = html_mod.unescape(name_match.group(1)) if name_match else ""

        emails = EMAIL_REGEX.findall(page_text)
        emails = [e for e in emails if e.lower() not in EMAIL_BLACKLIST
                  and not e.endswith((".png", ".jpg", ".svg", ".gif", ".css", ".js"))]

        raw_ig = INSTAGRAM_REGEX.findall(page_text)
        instagrams = [h for h in raw_ig if h.lower() not in IG_STOPWORDS]

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
    except Exception:
        return None


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


def process_playlist_urls(urls, keyword, existing_rows, seen_contacts, seen_ids):
    """Process a list of Spotify playlist URLs, scrape them, and add new contacts."""
    import time
    all_rows = list(existing_rows)
    new_count = 0

    for url in urls:
        match = re.search(r"open\.spotify\.com/playlist/([a-zA-Z0-9]{22})", url)
        if not match:
            continue

        pid = match.group(1)
        if pid in seen_ids:
            continue
        seen_ids.add(pid)

        data = scrape_playlist_page(pid)
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

        row = {
            "email": email_str,
            "instagram": ig_str,
            "playlist_name": data["name"],
            "playlist_url": f"https://open.spotify.com/playlist/{pid}",
            "keyword": keyword,
            "description_snippet": data["description"][:100].replace("\n", " ") if data["description"] else "",
        }
        all_rows.append(row)
        new_count += 1
        print(f"  NEW: {data['name']} | {email_str or ig_str}")

        time.sleep(random.uniform(0.5, 1.5))

    save_csv(all_rows)
    return all_rows, new_count
