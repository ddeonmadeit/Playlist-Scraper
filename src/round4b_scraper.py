"""Round 4b scraper - find remaining ~90 high-quality contacts.

Uses different search angle: Spotify playlist IDs from curator directories,
Telegram channels, and deeper blog scraping.
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

JUNK_DOMAINS = {
    "spotify.com", "sentry.wixpress.com", "sentry-next.wixpress.com",
    "playlistpush.com", "submithub.com", "example.com",
    "wixpress.com", "w3.org", "schema.org", "googleapis.com",
    "google.com", "facebook.com", "twitter.com", "youtube.com",
    "apple.com", "microsoft.com", "amazon.com",
    "cloudflare.com", "wordpress.com", "wordpress.org",
    "gravatar.com", "wp.com", "cdn.com",
    "sentry.io", "ingest.us.sentry.io", "sentry.rnd.infrapu.sh",
    "blogger.com", "yandex.ru", "mail.ru",
}
JUNK_EMAILS = {
    "example@gmail.com", "email@example.com", "your@email.com",
    "youremail@gmail.com", "name@email.com", "test@test.com",
    "noreply@spotify.com", "info@submithub.com", "noreply@blogger.com",
}

TOKEN_PLAYLISTS = [
    "37i9dQZF1DXcBWIGoYBM5M", "37i9dQZF1DX0XUsuxWHRQd",
    "37i9dQZF1DWXRqgorJj26U",
]
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]
FIELDNAMES = ["email", "instagram", "playlist_name", "playlist_url", "keyword",
              "description_snippet", "followers", "priority"]


def is_valid_curator_email(email):
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
    if email.endswith((".png", ".jpg", ".svg", ".gif", ".css", ".js", ".ico", ".webp")):
        return False
    tld = domain.split(".")[-1] if "." in domain else ""
    if len(tld) < 2 or len(tld) > 10:
        return False
    # Filter out clearly non-curator emails (hex hashes, sentry IDs)
    local = email_lower.split("@")[0]
    if len(local) > 20 and all(c in "0123456789abcdef" for c in local.replace("-", "")):
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
    try:
        resp = session.get(url, timeout=20, headers={
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,*/*",
        }, allow_redirects=True)
        if resp.status_code != 200 or len(resp.text) < 100:
            return [], [], []
        text = resp.text
        raw_emails = EMAIL_REGEX.findall(text)
        emails = [e for e in raw_emails if is_valid_curator_email(e)]
        pids = list(dict.fromkeys(re.findall(
            r"open\.spotify\.com/playlist/([a-zA-Z0-9]{22})", text)))
        base = urlparse(url)
        internal_links = []
        for m in re.finditer(r'href="([^"]*)"', text):
            href = m.group(1)
            if href.startswith("/") and not href.startswith("//"):
                full = f"{base.scheme}://{base.netloc}{href}"
                internal_links.append(full)
            elif href.startswith(f"{base.scheme}://{base.netloc}"):
                internal_links.append(href)
        return emails, pids, internal_links[:30]
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
                    for e in email.split(","):
                        seen_contacts.add(e.strip().lower())
                if ig:
                    for i in ig.split(","):
                        seen_contacts.add(i.strip().lower())
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
    target_new = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 90

    existing_rows, seen_contacts, seen_ids = load_existing()
    print(f"Loaded {len(existing_rows)} existing contacts")
    print(f"Target: {target_new} NEW contacts\n")

    session = requests.Session()
    session.verify = False

    token_mgr = TokenManager()
    if not token_mgr.get_token():
        print("ERROR: No token")
        return
    print("Token ready.\n")

    all_rows = list(existing_rows)
    total_new = 0

    # Different search angles this time
    search_queries = [
        # Telegram channels with playlist links
        "site:t.me spotify playlist submit music",
        "site:t.me spotify curator email",
        "site:t.me spotify playlists hip hop submit",

        # Specific curator directory sites
        "site:playlistsubmit.com rap",
        "site:playlistsubmit.com R&B",
        "site:playlistsubmit.com lofi",
        "site:playlistsubmit.com pop",
        "site:playlistsubmit.com hip hop",
        "site:dailyplaylists.com rap submit",
        "site:dailyplaylists.com R&B submit",
        "site:dailyplaylists.com lofi chill",
        "site:soundplate.com rap playlist submit",
        "site:soundplate.com R&B playlist submit",
        "site:soundplate.com hip hop submit",
        "site:soundplate.com lo-fi submit",
        "site:indiemono.com submit playlist",
        "site:artist.tools submit rap",
        "site:artist.tools submit hip hop",
        "site:artist.tools submit R&B",
        "site:artist.tools submit pop",
        "site:artist.tools submit lofi",
        "site:playlistlookup.com hip-hop",
        "site:playlistlookup.com R&B",
        "site:playlistlookup.com lofi",
        "site:playlistlookup.com rap",
        "site:playlistlookup.com pop",

        # Music blog curator roundups
        "curator roundup spotify playlist email rap 2025",
        "curator roundup spotify playlist email R&B 2025",
        "best independent spotify playlists email 2026",
        "music blog list spotify curators hip hop email",
        "free music submission spotify curators contact 2026",

        # Different keyword patterns
        "spotify playlist \"submit your music\" email @gmail.com",
        "spotify playlist \"send your music\" email contact",
        "spotify playlist \"accepting submissions\" email @gmail.com",
        "spotify playlist \"open for submissions\" contact email",
        "spotify curator \"contact us\" email playlist rap",
        "spotify playlist \"DM us\" instagram rap hip hop",
        "spotify playlist description \"submit\" email curator",

        # Niche genre angles not well-covered yet
        "K-pop spotify playlist curator submit email",
        "country rap spotify playlist submit email",
        "hyper pop spotify playlist curator email",
        "jersey club spotify playlist submit email",
        "baile funk spotify playlist curator email",
        "uk drill spotify playlist submit email",
        "chicago drill spotify playlist email",
        "detroit rap spotify playlist submit email",
        "memphis rap spotify playlist email",
        "chopped and screwed spotify playlist curator",
        "vapor soul spotify playlist submit",
        "future soul spotify playlist email",
        "jazz rap spotify playlist curator email 2025",
        "experimental hip hop spotify playlist email",
        "instrumental hip hop spotify playlist email submit",
        "trip hop spotify playlist curator email",
        "downtempo spotify playlist submit email",
        "ambient hip hop spotify playlist email",
        "synthwave spotify playlist curator email",
        "retrowave spotify playlist submit email",
        "chillwave spotify playlist email submit",
        "vaporwave spotify playlist curator contact",

        # Artist community forums
        "artist forum spotify playlist submit email rap",
        "music producer spotify playlist email submit",
        "beatmaker spotify playlist curator email",
        "songwriter spotify playlist submit email",
        "rapper spotify playlist email submit free",
        "singer spotify playlist curator contact email",
    ]

    scraped_urls = set()

    for qi, query in enumerate(search_queries):
        if total_new >= target_new:
            break

        print(f"\n[{qi+1}/{len(search_queries)}] {query[:65]}... (new: {total_new}/{target_new}, total: {len(all_rows)})")

        try:
            with DDGS() as ddgs:
                results = ddgs.text(query, max_results=20)
        except Exception as e:
            if "Ratelimit" in str(e):
                print("  DDG rate limited, waiting 60s...")
                time.sleep(60)
                continue
            print(f"  Search error: {e}")
            time.sleep(5)
            continue

        for r in results:
            if total_new >= target_new:
                break

            url = r.get("href", "") or r.get("link", "")
            if not url or url in scraped_urls:
                continue
            if "spotify.com" in url and "open.spotify.com/playlist" not in url:
                continue
            scraped_urls.add(url)

            # If it's a spotify playlist URL directly, grab its data
            pid_match = re.search(r"open\.spotify\.com/playlist/([a-zA-Z0-9]{22})", url)
            if pid_match:
                pid = pid_match.group(1)
                if pid in seen_ids:
                    continue
                seen_ids.add(pid)
                data = get_playlist_data(session, token_mgr, pid)
                if data and not data["editorial"] and (data["emails"] or data["instagrams"]):
                    emails = [e for e in data["emails"] if is_valid_curator_email(e)]
                    email_str = ", ".join(emails[:3])
                    ig_str = ", ".join(data["instagrams"][:3])
                    key = (email_str or ig_str).lower()
                    if key not in seen_contacts:
                        seen_contacts.add(key)
                        for e in emails:
                            seen_contacts.add(e.lower())
                        row = {
                            "email": email_str,
                            "instagram": ig_str,
                            "playlist_name": data["name"],
                            "playlist_url": f"https://open.spotify.com/playlist/{pid}",
                            "keyword": query[:50],
                            "description_snippet": data["description"][:100].replace("\n", " ") if data["description"] else "",
                            "followers": "",
                            "priority": "high",
                        }
                        all_rows.append(row)
                        total_new += 1
                        print(f"    HIT [DIRECT]: {data['name'][:40]} | {email_str or ig_str}")
                time.sleep(random.uniform(0.3, 0.6))
                continue

            # Otherwise scrape the page
            page_emails, page_pids, internal_links = scrape_page(url, session)
            new_page_emails = [e for e in page_emails if e.lower() not in seen_contacts]
            new_pids = [p for p in page_pids if p not in seen_ids]

            snippet = r.get("body", "") or ""
            snippet_emails = [e for e in EMAIL_REGEX.findall(snippet)
                             if is_valid_curator_email(e) and e.lower() not in seen_contacts]
            all_new_emails = list(set(new_page_emails + snippet_emails))

            if not all_new_emails and not new_pids:
                continue

            print(f"  {url[:70]}...")
            print(f"  Found {len(all_new_emails)} new emails, {len(new_pids)} new playlists")

            # Pair emails with playlists when possible
            if new_pids:
                for pid in new_pids[:20]:
                    if total_new >= target_new:
                        break
                    seen_ids.add(pid)
                    data = get_playlist_data(session, token_mgr, pid)
                    if not data or data["editorial"]:
                        continue

                    merged_emails = list(set(data["emails"] + all_new_emails[:3]))
                    merged_emails = [e for e in merged_emails if is_valid_curator_email(e)]
                    igs = data["instagrams"]

                    if not merged_emails and not igs:
                        continue

                    email_str = ", ".join(merged_emails[:3])
                    ig_str = ", ".join(igs[:3])
                    key = (email_str or ig_str).lower()
                    if key in seen_contacts:
                        continue
                    seen_contacts.add(key)
                    for e in merged_emails:
                        seen_contacts.add(e.lower())

                    row = {
                        "email": email_str,
                        "instagram": ig_str,
                        "playlist_name": data["name"],
                        "playlist_url": f"https://open.spotify.com/playlist/{pid}",
                        "keyword": query[:50],
                        "description_snippet": data["description"][:100].replace("\n", " ") if data["description"] else "",
                        "followers": "",
                        "priority": "high",
                    }
                    all_rows.append(row)
                    total_new += 1
                    print(f"    HIT: {data['name'][:40]} | {email_str or ig_str}")
                    time.sleep(random.uniform(0.2, 0.5))

            # Emails without playlists
            if all_new_emails:
                for email in all_new_emails[:5]:
                    if total_new >= target_new:
                        break
                    if email.lower() in seen_contacts:
                        continue
                    seen_contacts.add(email.lower())
                    row = {
                        "email": email,
                        "instagram": "",
                        "playlist_name": "",
                        "playlist_url": "",
                        "keyword": query[:50],
                        "description_snippet": f"Found on {urlparse(url).netloc}",
                        "followers": "",
                        "priority": "",
                    }
                    all_rows.append(row)
                    total_new += 1
                    print(f"    + {email}")

            # Follow internal links
            for link in internal_links[:8]:
                if link in scraped_urls or total_new >= target_new:
                    continue
                if not any(kw in link.lower() for kw in ["curator", "playlist", "submit", "contact", "email", "music", "genre", "rap", "hip-hop", "r-b", "lofi"]):
                    continue
                scraped_urls.add(link)
                sub_emails, sub_pids, _ = scrape_page(link, session)
                new_sub_emails = [e for e in sub_emails if is_valid_curator_email(e) and e.lower() not in seen_contacts]
                new_sub_pids = [p for p in sub_pids if p not in seen_ids]

                if new_sub_pids:
                    for pid in new_sub_pids[:10]:
                        if total_new >= target_new:
                            break
                        seen_ids.add(pid)
                        data = get_playlist_data(session, token_mgr, pid)
                        if not data or data["editorial"]:
                            continue
                        merged = list(set(data["emails"] + new_sub_emails[:3]))
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
                            "keyword": query[:50],
                            "description_snippet": data["description"][:100].replace("\n", " ") if data["description"] else "",
                            "followers": "",
                            "priority": "high",
                        }
                        all_rows.append(row)
                        total_new += 1
                        print(f"    HIT [SUB]: {data['name'][:40]} | {email_str or ig_str}")
                        time.sleep(random.uniform(0.2, 0.5))
                elif new_sub_emails:
                    for email in new_sub_emails[:3]:
                        if total_new >= target_new:
                            break
                        if email.lower() in seen_contacts:
                            continue
                        seen_contacts.add(email.lower())
                        row = {
                            "email": email,
                            "instagram": "",
                            "playlist_name": "",
                            "playlist_url": "",
                            "keyword": query[:50],
                            "description_snippet": f"Found on {urlparse(link).netloc}",
                            "followers": "",
                            "priority": "",
                        }
                        all_rows.append(row)
                        total_new += 1
                        print(f"    + {email} (subpage)")
                time.sleep(1)

            if total_new > 0 and total_new % 10 == 0:
                save_csv(all_rows)
                print(f"  [SAVED] {len(all_rows)} total")

        time.sleep(random.uniform(8, 15))

    # Final save
    count = save_csv(all_rows)
    print(f"\n{'=' * 60}")
    print(f"DONE! +{total_new} new contacts. {count} total in output.csv")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
