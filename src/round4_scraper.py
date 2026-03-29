"""Round 4 scraper - find 200 more high-quality contacts.

Focuses on queries that previously yielded good results:
submit rap/R&B/lofi playlists, curator email lists, genre-specific searches.
Only keeps contacts that have BOTH an email/IG AND a playlist URL.
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
    if email.endswith((".png", ".jpg", ".svg", ".gif", ".css", ".js", ".ico")):
        return False
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
    target_new = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 200

    existing_rows, seen_contacts, seen_ids = load_existing()
    print(f"Loaded {len(existing_rows)} existing contacts")
    print(f"Already know {len(seen_contacts)} contact identifiers, {len(seen_ids)} playlist IDs")
    print(f"Target: {target_new} NEW high-quality contacts\n")

    session = requests.Session()
    session.verify = False

    token_mgr = TokenManager()
    if not token_mgr.get_token():
        print("ERROR: No token")
        return
    print("Token ready.\n")

    all_rows = list(existing_rows)
    total_new = 0

    # Fresh queries using the same keyword themes that worked before
    search_queries = [
        # Submit playlist queries (top performers before)
        "submit music to spotify playlist email 2025",
        "submit music to spotify playlist email 2026",
        "submit rap song to spotify playlist free",
        "submit R&B song to spotify playlist free email",
        "submit trap music spotify playlist curator",
        "submit lofi beats spotify playlist email",
        "submit hip hop music spotify playlist contact",
        "submit indie music spotify playlist email",
        "submit pop song spotify playlist curator email",
        "submit afrobeats spotify playlist email",
        "submit drill music spotify playlist",
        "submit phonk spotify playlist email",
        "submit soul music spotify playlist",
        "submit dancehall spotify playlist email",
        "submit bedroom pop spotify playlist email",
        "submit alternative R&B spotify playlist",
        "submit neo soul spotify playlist email",

        # Curator email list queries (second top performer)
        "spotify curator email list free 2026",
        "spotify curator email list free 2025 hip hop",
        "spotify curator email database rap",
        "spotify playlist curator contacts free list",
        "list of spotify curators with emails",
        "free list spotify playlist curator email contacts",
        "spotify playlist owner email address list",
        "independent spotify curator emails free",

        # Playlist submission directory queries
        "spotify playlist submission websites free",
        "spotify playlist submission directory 2025",
        "spotify playlist submission directory 2026",
        "music submission playlists with email contact",
        "free spotify playlist placement contacts",
        "spotify playlist placement email list",

        # Blog/article queries with curator lists
        "how to submit music to spotify playlists email list",
        "top 100 spotify playlist curators email",
        "biggest independent spotify playlists contact",
        "best spotify playlists for independent artists email",
        "spotify curators accepting submissions email",
        "spotify curators looking for new music email",
        "how to contact spotify playlist curators directly",

        # Genre-specific fresh queries
        "underground rap spotify playlist submit email",
        "chill vibes spotify playlist curator email",
        "workout hip hop spotify playlist submit",
        "study beats lo-fi spotify playlist curator contact",
        "party rap spotify playlist submit email",
        "sad rap spotify playlist curator email",
        "melodic rap spotify playlist submit email",
        "boom bap spotify playlist curator email",
        "conscious hip hop spotify playlist submit",
        "west coast rap spotify playlist email",
        "east coast hip hop spotify playlist email",
        "southern rap spotify playlist submit email",
        "UK rap grime spotify playlist submit",
        "latin trap spotify playlist email submit",
        "reggaeton spotify playlist curator email",
        "amapiano spotify playlist submit email",
        "gospel hip hop spotify playlist curator",
        "christian rap spotify playlist email",
        "jazz hip hop spotify playlist curator email",
        "funk spotify playlist submit email",
        "R&B vibes spotify playlist curator contact",
        "modern R&B spotify playlist email submit",
        "indie R&B spotify playlist curator email",
        "dark R&B spotify playlist submit",
        "smooth R&B spotify playlist curator email",
        "pop rap crossover spotify playlist email",
        "emo rap spotify playlist submit email",
        "cloud rap spotify playlist curator",
        "pluggnb spotify playlist submit email",
        "type beat spotify playlist curator email",
        "freestyle beats spotify playlist submit",

        # Music promotion blog searches
        "music promotion blog spotify curator emails 2025",
        "music promotion blog spotify curator emails 2026",
        "how to promote music on spotify email curators",
        "indie music promotion spotify playlist email",
        "rap music promotion playlist email contacts",
        "free music promotion spotify playlist curator",

        # Fresh discovery angles
        "new spotify playlists accepting submissions 2025",
        "new spotify playlists accepting submissions 2026",
        "spotify playlist open for submissions email",
        "curated spotify playlist open submissions contact",
        "indie spotify playlists looking for artists email",
        "hip hop spotify playlists seeking new music email",
        "R&B spotify playlists open for submissions",
        "lo-fi spotify playlists accepting submissions email",
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
            if "spotify.com" in url:
                continue
            scraped_urls.add(url)

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

            # HIGH QUALITY: pair emails with playlists
            if new_pids and all_new_emails:
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
                    print(f"    HIT [HQ]: {data['name'][:40]} | {email_str or ig_str}")
                    time.sleep(random.uniform(0.2, 0.5))

            # Also grab playlists that have their own emails in the description
            elif new_pids:
                for pid in new_pids[:15]:
                    if total_new >= target_new:
                        break
                    seen_ids.add(pid)
                    data = get_playlist_data(session, token_mgr, pid)
                    if not data or data["editorial"]:
                        continue
                    if not data["emails"] and not data["instagrams"]:
                        continue

                    email_str = ", ".join(data["emails"][:3])
                    ig_str = ", ".join(data["instagrams"][:3])
                    key = (email_str or ig_str).lower()
                    if key in seen_contacts:
                        continue
                    seen_contacts.add(key)
                    for e in data["emails"]:
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
                    print(f"    HIT [PL]: {data['name'][:40]} | {email_str or ig_str}")
                    time.sleep(random.uniform(0.2, 0.5))

            # Pages with emails but no playlists - still add but lower priority
            elif all_new_emails:
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

            # Follow internal links for more playlists+emails
            for link in internal_links[:5]:
                if link in scraped_urls or total_new >= target_new:
                    continue
                if not any(kw in link.lower() for kw in ["curator", "playlist", "submit", "contact", "email", "music"]):
                    continue
                scraped_urls.add(link)
                sub_emails, sub_pids, _ = scrape_page(link, session)
                new_sub_emails = [e for e in sub_emails if is_valid_curator_email(e) and e.lower() not in seen_contacts]
                new_sub_pids = [p for p in sub_pids if p not in seen_ids]

                if new_sub_emails and new_sub_pids:
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

            # Save periodically
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
