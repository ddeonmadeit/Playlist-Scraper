"""Batch scrape Spotify playlist pages for contact info.

Reads playlist IDs from a file, scrapes each page directly (no API needed),
and appends new contacts to output.csv.
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


def scrape_playlist_page(session, playlist_id):
    """Scrape contact info from a Spotify playlist page."""
    url = f"https://open.spotify.com/playlist/{playlist_id}"
    try:
        session.headers["User-Agent"] = random.choice(USER_AGENTS)
        resp = session.get(url, timeout=20)
        if resp.status_code != 200:
            return None

        page_text = resp.text

        name_match = re.search(r'property="og:title"\s+content="([^"]*)"', page_text)
        name = html_mod.unescape(name_match.group(1)) if name_match else ""

        emails = EMAIL_REGEX.findall(page_text)
        emails = [e for e in emails if e.lower() not in EMAIL_BLACKLIST
                  and not e.endswith((".png", ".jpg", ".svg", ".gif", ".css", ".js"))]

        raw_ig = INSTAGRAM_REGEX.findall(page_text)
        instagrams = [h for h in raw_ig if h.lower() not in IG_STOPWORDS and len(h) > 2]

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


def main():
    ids_file = sys.argv[1] if len(sys.argv) > 1 else "playlist_ids_to_scrape.txt"
    keyword_label = sys.argv[2] if len(sys.argv) > 2 else "web_search"

    with open(ids_file) as f:
        playlist_ids = [line.strip() for line in f if line.strip() and len(line.strip()) >= 20]

    print(f"Loaded {len(playlist_ids)} playlist IDs to scrape")

    existing_rows, seen_contacts, seen_ids = load_existing()
    print(f"Loaded {len(existing_rows)} existing entries ({len(seen_contacts)} unique contacts)")

    session = requests.Session()
    session.verify = False
    session.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })

    all_rows = list(existing_rows)
    total_new = 0
    skipped = 0
    errors = 0

    for i, pid in enumerate(playlist_ids):
        if pid in seen_ids:
            skipped += 1
            continue
        seen_ids.add(pid)

        data = scrape_playlist_page(session, pid)
        if not data:
            errors += 1
            time.sleep(1)
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
            "keyword": keyword_label,
            "description_snippet": snippet,
        }
        all_rows.append(row)
        total_new += 1
        print(f"  [{i+1}/{len(playlist_ids)}] HIT: {data['name']} | {email_str or ig_str}")

        # Save every 5 new contacts
        if total_new % 5 == 0:
            save_csv(all_rows)

        time.sleep(random.uniform(0.5, 1.5))

    count = save_csv(all_rows)
    print(f"\nDONE! +{total_new} new | {count} total | {skipped} skipped | {errors} errors")


if __name__ == "__main__":
    main()
