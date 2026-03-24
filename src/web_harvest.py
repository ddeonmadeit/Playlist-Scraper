"""Web harvest scraper - aggressively scrapes music blogs and curator sites.

Searches DDG for pages containing curator emails and scrapes them.
Uses multiple search queries and follows internal links.
"""

import csv
import os
import re
import sys
import time
import random
from urllib.parse import urljoin, urlparse

import requests
import urllib3
from ddgs import DDGS

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

# Domains that never have real curator emails
JUNK_DOMAINS = {
    "spotify.com", "sentry.wixpress.com", "sentry-next.wixpress.com",
    "playlistpush.com", "submithub.com", "example.com",
    "wixpress.com", "w3.org", "schema.org", "googleapis.com",
    "google.com", "facebook.com", "twitter.com", "youtube.com",
    "apple.com", "microsoft.com", "amazon.com",
    "cloudflare.com", "wordpress.com", "wordpress.org",
    "gravatar.com", "wp.com", "cdn.com",
}
JUNK_EMAILS = {
    "example@gmail.com", "email@example.com", "your@email.com",
    "youremail@gmail.com", "name@email.com", "test@test.com",
    "noreply@spotify.com", "info@submithub.com",
}

TOKEN_PLAYLISTS = [
    "37i9dQZF1DXcBWIGoYBM5M", "37i9dQZF1DX0XUsuxWHRQd",
    "37i9dQZF1DWXRqgorJj26U",
]
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]
FIELDNAMES = ["email", "instagram", "playlist_name", "playlist_url", "keyword",
              "description_snippet", "followers", "priority"]


def is_valid_curator_email(email):
    """Filter out junk emails."""
    email_lower = email.lower().strip()
    if email_lower in JUNK_EMAILS:
        return False
    domain = email_lower.split("@")[-1] if "@" in email_lower else ""
    if domain in JUNK_DOMAINS:
        return False
    if any(domain.endswith(f".{jd}") for jd in JUNK_DOMAINS):
        return False
    if len(email) < 6:
        return False
    if email.endswith((".png", ".jpg", ".svg", ".gif", ".css", ".js", ".ico")):
        return False
    # Must have valid TLD
    tld = domain.split(".")[-1] if "." in domain else ""
    if len(tld) < 2 or len(tld) > 10:
        return False
    return True


class TokenManager:
    def __init__(self):
        self.token = None
        self.session = requests.Session()
        self.session.verify = False

    def get_token(self):
        return self.token or self.refresh()

    def refresh(self):
        pid = random.choice(TOKEN_PLAYLISTS)
        self.session.headers["User-Agent"] = random.choice(USER_AGENTS)
        try:
            resp = self.session.get(
                f"https://open.spotify.com/embed/playlist/{pid}", timeout=15)
            tokens = re.findall(r'"accessToken":"([^"]+)"', resp.text)
            if tokens:
                self.token = tokens[0]
                return self.token
        except Exception:
            pass
        return None


def get_playlist_data(session, token_mgr, playlist_id):
    token = token_mgr.get_token()
    if not token:
        return None
    try:
        resp = session.get(
            f"https://spclient.wg.spotify.com/playlist/v2/playlist/{playlist_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15)
        if resp.status_code == 401:
            token_mgr.refresh()
            token = token_mgr.get_token()
            if not token:
                return None
            resp = session.get(
                f"https://spclient.wg.spotify.com/playlist/v2/playlist/{playlist_id}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=15)
        if resp.status_code != 200:
            return None
        text = resp.content.decode("utf-8", errors="ignore")
        strings = re.findall(r"[\x20-\x7E]{3,}", text)
        name, desc = "", ""
        for s in strings:
            if len(s) >= 3 and not name:
                name = s.strip()
                continue
            if len(s) >= 10 and not desc:
                desc = s.strip()
                break
        emails = [e for e in EMAIL_REGEX.findall(text) if is_valid_curator_email(e)]
        raw_ig = INSTAGRAM_REGEX.findall(text)
        instagrams = [h for h in raw_ig if h.lower() not in IG_STOPWORDS and len(h) > 2]
        is_editorial = any(m in text.lower() for m in ["spotify:user:spotify", "isalgotorial"])
        return {"name": name, "description": desc, "emails": list(set(emails)),
                "instagrams": list(set(instagrams)), "editorial": is_editorial}
    except Exception:
        return None


def scrape_page(url, session):
    """Scrape a web page for emails and Spotify playlist URLs."""
    try:
        resp = session.get(url, timeout=20, headers={
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,*/*",
        }, allow_redirects=True)
        if resp.status_code != 200 or len(resp.text) < 100:
            return [], [], []
        text = resp.text

        # Extract emails
        raw_emails = EMAIL_REGEX.findall(text)
        emails = [e for e in raw_emails if is_valid_curator_email(e)]

        # Extract playlist IDs
        pids = list(dict.fromkeys(re.findall(
            r"open\.spotify\.com/playlist/([a-zA-Z0-9]{22})", text)))

        # Extract internal links to follow
        base = urlparse(url)
        internal_links = []
        for m in re.finditer(r'href="([^"]*)"', text):
            href = m.group(1)
            if href.startswith("/") and not href.startswith("//"):
                full = f"{base.scheme}://{base.netloc}{href}"
                internal_links.append(full)
            elif href.startswith(f"{base.scheme}://{base.netloc}"):
                internal_links.append(href)

        return emails, pids, internal_links[:20]
    except Exception:
        return [], [], []


def load_existing(filename="output.csv"):
    rows = []
    seen_contacts = set()
    seen_ids = set()
    try:
        with open(filename, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if "followers" not in row:
                    row["followers"] = ""
                if "priority" not in row:
                    row["priority"] = ""
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
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main():
    target = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 1500

    existing_rows, seen_contacts, seen_ids = load_existing()
    print(f"Loaded {len(existing_rows)} existing | Need {max(0, target - len(existing_rows))} more\n")

    session = requests.Session()
    session.verify = False

    token_mgr = TokenManager()
    if not token_mgr.get_token():
        print("ERROR: No token")
        return
    print("Token ready.\n")

    all_rows = list(existing_rows)
    total_new = 0

    # ── DDG queries to find pages with curator email lists ──
    search_queries = [
        # Direct email list pages
        "spotify playlist curator email list 2024",
        "spotify playlist curator email list 2025",
        "spotify playlist curator contact database",
        "free spotify curator email list hip hop",
        "free spotify curator email list R&B",
        "free spotify curator email list lofi",
        "free spotify curator email list pop",
        "free spotify curator email list indie",
        "spotify playlist submission email addresses",
        "spotify curator emails free download",
        "spotify independent curator contact info",
        "best spotify playlists submit music email",
        "hip hop spotify curators email list free",
        "lofi chill beats curators email contact",
        "R&B soul spotify curators contact",
        "rap trap spotify curators email",
        "indie pop curators spotify email list",
        "underground hip hop curators email",
        "spotify playlist owners email list",
        # Blog posts with embedded lists
        "how to find spotify playlist curator emails",
        "top spotify curators contact information",
        "spotify playlist promotion contacts free",
        "music promotion spotify curator emails",
        "get your music on spotify playlists curator contact",
        "submit music to curators free email list",
        "spotify playlist curator directory 2024",
        "spotify playlist curator directory 2025",
        # Forum posts
        "reddit spotify playlist curator email",
        "reddit submit music playlist email",
        "music forum spotify curator email list",
        # Social media
        "twitter spotify curator email list",
        "tiktok spotify curator email list",
        # Blog articles
        "best blogs for finding spotify curators",
        "music blog spotify playlist submission emails",
        "indie music blog playlist submission contact",
        # Specific music promotion sites
        "daily playlists curator email list",
        "soundplate curator email list",
        "indiemono curator email list",
        "playlist map curator emails",
        "tunebump curator email list",
        # Year-specific
        "spotify playlist curators 2025 email contact list",
        "spotify playlist curators 2024 email contact free",
        "new spotify curators 2025 accepting music",
        # Genre-specific pages
        "afrobeats spotify playlist curators contact",
        "drill spotify playlist curators email",
        "phonk spotify playlist curators email",
        "vaporwave spotify playlist curators contact",
        "jazz hop spotify playlist curators email",
        "neo soul spotify playlist curators contact",
        "bedroom pop spotify playlist curators email",
        "boom bap spotify playlist curators contact",
    ]

    # Track all scraped URLs to avoid duplicates
    scraped_urls = set()

    for qi, query in enumerate(search_queries):
        if len(all_rows) >= target:
            break

        print(f"\n[{qi+1}/{len(search_queries)}] {query[:60]}... (total: {len(all_rows)})")

        try:
            with DDGS() as ddgs:
                results = ddgs.text(query, max_results=15)
        except Exception as e:
            if "Ratelimit" in str(e):
                print("  DDG rate limited, waiting 60s...")
                time.sleep(60)
                continue
            time.sleep(5)
            continue

        for r in results:
            if len(all_rows) >= target:
                break

            url = r.get("href", "") or r.get("link", "")
            if not url or url in scraped_urls:
                continue
            if "spotify.com" in url:
                continue  # Skip Spotify pages themselves
            scraped_urls.add(url)

            # Check snippet for emails first
            snippet = r.get("body", "") or ""
            snippet_emails = [e for e in EMAIL_REGEX.findall(snippet)
                             if is_valid_curator_email(e) and e.lower() not in seen_contacts]

            # Scrape the page
            page_emails, page_pids, internal_links = scrape_page(url, session)
            new_page_emails = [e for e in page_emails if e.lower() not in seen_contacts]

            if not new_page_emails and not snippet_emails:
                continue

            all_new_emails = list(set(new_page_emails + snippet_emails))
            new_pids = [p for p in page_pids if p not in seen_ids]

            print(f"  {url[:70]}...")
            print(f"  Found {len(all_new_emails)} new emails, {len(new_pids)} new playlists")

            # If page has both playlists and emails, try to associate them
            if new_pids:
                for pid in new_pids[:15]:
                    if len(all_rows) >= target:
                        break
                    seen_ids.add(pid)
                    data = get_playlist_data(session, token_mgr, pid)
                    if not data or data["editorial"]:
                        continue

                    # Merge page emails + playlist emails
                    merged = list(set(data["emails"] + all_new_emails[:3]))
                    merged = [e for e in merged if is_valid_curator_email(e)]
                    igs = data["instagrams"]

                    if not merged and not igs:
                        continue

                    email_str = ", ".join(merged[:3])
                    ig_str = ", ".join(igs[:3])
                    key = (email_str or ig_str).lower()
                    if key in seen_contacts:
                        continue
                    seen_contacts.add(key)
                    for e in merged:
                        seen_contacts.add(e.lower())

                    row = {
                        "email": email_str,
                        "instagram": ig_str,
                        "playlist_name": data["name"],
                        "playlist_url": f"https://open.spotify.com/playlist/{pid}",
                        "keyword": "Web Harvest",
                        "description_snippet": data["description"][:100].replace("\n", " ") if data["description"] else "",
                        "followers": "",
                        "priority": "",
                    }
                    all_rows.append(row)
                    total_new += 1
                    print(f"    HIT: {data['name'][:40]} | {email_str or ig_str}")
                    time.sleep(random.uniform(0.2, 0.5))

            # Add remaining emails as standalone contacts
            for email in all_new_emails:
                if len(all_rows) >= target:
                    break
                if email.lower() in seen_contacts:
                    continue
                seen_contacts.add(email.lower())
                row = {
                    "email": email,
                    "instagram": "",
                    "playlist_name": "",
                    "playlist_url": "",
                    "keyword": "Web Harvest",
                    "description_snippet": f"Found on {urlparse(url).netloc}",
                    "followers": "",
                    "priority": "",
                }
                all_rows.append(row)
                total_new += 1
                print(f"    + {email}")

            # Follow promising internal links (curator list pages)
            for link in internal_links[:5]:
                if link in scraped_urls or len(all_rows) >= target:
                    continue
                if not any(kw in link.lower() for kw in ["curator", "playlist", "submit", "contact", "email"]):
                    continue
                scraped_urls.add(link)
                sub_emails, sub_pids, _ = scrape_page(link, session)
                new_sub = [e for e in sub_emails if is_valid_curator_email(e) and e.lower() not in seen_contacts]
                for email in new_sub:
                    if len(all_rows) >= target:
                        break
                    seen_contacts.add(email.lower())
                    row = {
                        "email": email,
                        "instagram": "",
                        "playlist_name": "",
                        "playlist_url": "",
                        "keyword": "Web Harvest",
                        "description_snippet": f"Found on {urlparse(link).netloc}",
                        "followers": "",
                        "priority": "",
                    }
                    all_rows.append(row)
                    total_new += 1
                    print(f"    + {email} (subpage)")
                time.sleep(1)

            if total_new > 0 and total_new % 5 == 0:
                save_csv(all_rows)

        time.sleep(random.uniform(8, 15))

    # Final save
    count = save_csv(all_rows)
    print(f"\n{'=' * 60}")
    print(f"DONE! +{total_new} new contacts. {count} total in output.csv")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
