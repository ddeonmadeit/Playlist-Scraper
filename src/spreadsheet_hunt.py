"""Hunt for Google Sheets/Docs with curator email lists and scrape indiemono playlists."""

import csv
import os
import re
import sys
import time
import random

import requests
import urllib3
from ddgs import DDGS

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
JUNK_DOMAINS = {
    "spotify.com", "sentry.wixpress.com", "sentry-next.wixpress.com",
    "w3.org", "schema.org", "googleapis.com", "google.com", "facebook.com",
    "twitter.com", "youtube.com", "apple.com", "microsoft.com", "amazon.com",
    "cloudflare.com", "wordpress.org", "gravatar.com", "wixpress.com",
    "example.com", "playlistpush.com", "submithub.com",
}
JUNK_EMAILS = {
    "example@gmail.com", "email@example.com", "your@email.com",
    "youremail@gmail.com", "name@email.com", "test@test.com",
}

TOKEN_PLAYLISTS = ["37i9dQZF1DXcBWIGoYBM5M", "37i9dQZF1DX0XUsuxWHRQd"]
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]
FIELDNAMES = ["email", "instagram", "playlist_name", "playlist_url", "keyword",
              "description_snippet", "followers", "priority"]


def is_valid_email(email):
    e = email.lower().strip()
    if e in JUNK_EMAILS:
        return False
    domain = e.split("@")[-1] if "@" in e else ""
    if domain in JUNK_DOMAINS or any(domain.endswith(f".{jd}") for jd in JUNK_DOMAINS):
        return False
    if len(email) < 6 or email.endswith((".png", ".jpg", ".svg", ".gif", ".css", ".js")):
        return False
    tld = domain.split(".")[-1] if "." in domain else ""
    return 2 <= len(tld) <= 10


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
            resp = self.session.get(f"https://open.spotify.com/embed/playlist/{pid}", timeout=15)
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
            headers={"Authorization": f"Bearer {token}"}, timeout=15)
        if resp.status_code == 401:
            token_mgr.refresh()
            token = token_mgr.get_token()
            if not token: return None
            resp = session.get(
                f"https://spclient.wg.spotify.com/playlist/v2/playlist/{playlist_id}",
                headers={"Authorization": f"Bearer {token}"}, timeout=15)
        if resp.status_code != 200:
            return None
        text = resp.content.decode("utf-8", errors="ignore")
        strings = re.findall(r"[\x20-\x7E]{3,}", text)
        name, desc = "", ""
        for s in strings:
            if len(s) >= 3 and not name: name = s.strip(); continue
            if len(s) >= 10 and not desc: desc = s.strip(); break
        emails = [e for e in EMAIL_REGEX.findall(text) if is_valid_email(e)]
        is_editorial = any(m in text.lower() for m in ["spotify:user:spotify", "isalgotorial"])
        return {"name": name, "description": desc, "emails": list(set(emails)), "editorial": is_editorial}
    except Exception:
        return None


def fetch_page(url, session):
    try:
        resp = session.get(url, timeout=25, headers={
            "User-Agent": random.choice(USER_AGENTS), "Accept": "text/html,*/*"
        }, allow_redirects=True)
        return resp.text if resp.status_code == 200 else ""
    except Exception:
        return ""


def load_existing(filename="output.csv"):
    rows, seen_contacts, seen_ids = [], set(), set()
    try:
        with open(filename, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if "followers" not in row: row["followers"] = ""
                if "priority" not in row: row["priority"] = ""
                rows.append(row)
                url = row.get("playlist_url", "")
                if "/playlist/" in url:
                    seen_ids.add(url.split("/playlist/")[-1].split("?")[0])
                email = row.get("email", "").strip()
                ig = row.get("instagram", "").strip()
                if email: seen_contacts.add(email.lower())
                if ig: seen_contacts.add(ig.lower())
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
    print(f"Loaded {len(existing_rows)} | Need {max(0, target - len(existing_rows))} more\n")

    session = requests.Session()
    session.verify = False
    token_mgr = TokenManager()
    if not token_mgr.get_token():
        print("ERROR: No token"); return
    print("Token ready.\n")

    all_rows = list(existing_rows)
    total_new = 0

    # ── Phase 1: Hunt for Google Docs/Sheets with email lists ──
    print("=" * 60)
    print("PHASE 1: Hunting for spreadsheets & docs with curator emails")
    print("=" * 60)

    hunt_queries = [
        # Google Sheets/Docs
        "spotify playlist curator email list site:docs.google.com",
        "spotify playlist submission contacts site:docs.google.com",
        "music curator email spreadsheet site:docs.google.com",
        "playlist curator contact list site:docs.google.com",
        "indie music email list site:docs.google.com",
        "band email list site:docs.google.com",
        "music submission contacts site:docs.google.com",
        "music promotion email list site:docs.google.com",
        "music blog email list site:docs.google.com",
        "music press contacts site:docs.google.com",
        "spotify playlist email list site:docs.google.com",
        "music industry contacts email site:docs.google.com",
        "record label email list site:docs.google.com",
        "music PR email list site:docs.google.com",
        "DJ email list site:docs.google.com",
        "rapper email list site:docs.google.com",
        "producer email contact list site:docs.google.com",
        # Notion pages
        "spotify curator email site:notion.site",
        "playlist submission contacts site:notion.site",
        "music curator database site:notion.site",
        "spotify playlist curator site:notion.so",
        # Airtable
        "spotify curator email site:airtable.com",
        "playlist submission site:airtable.com",
        # Other platforms
        "spotify curator email list filetype:xlsx",
        "spotify curator email list filetype:csv",
        "music curator contact list pdf",
        # Reddit / forums
        "spotify playlist curators email list reddit",
        "free spotify curator contacts reddit",
        "playlist submission email list reddit",
        # Blog posts with embedded email lists
        "\"spotify playlist curators\" \"email\" \"@gmail.com\" list",
        "\"playlist curators\" \"contact\" \"@gmail\" list 2024",
        "\"playlist curators\" \"contact\" \"@gmail\" list 2025",
        "spotify playlist \"email us\" \"submit\" contact list",
        "best spotify curators email free list",
        "spotify curator outreach email list free",
        # Music-specific sites
        "site:musicgateway.com spotify curator email",
        "site:mysphera.com spotify curator",
        "site:groover.co spotify playlist curator",
        "site:toneden.io spotify playlist curators",
        "site:chartmetric.com spotify curator",
    ]

    scraped_urls = set()

    for qi, query in enumerate(hunt_queries):
        if len(all_rows) >= target:
            break
        print(f"\n[{qi+1}/{len(hunt_queries)}] {query[:65]}...")

        try:
            with DDGS() as ddgs:
                results = ddgs.text(query, max_results=15)
        except Exception as e:
            if "Ratelimit" in str(e):
                print("  DDG throttled, waiting 60s...")
                time.sleep(60)
                continue
            time.sleep(5)
            continue

        for r in results:
            url = r.get("href", "") or ""
            if not url or url in scraped_urls:
                continue
            scraped_urls.add(url)

            # Check snippet for emails
            snippet = r.get("body", "") or ""
            snippet_emails = [e for e in EMAIL_REGEX.findall(snippet)
                              if is_valid_email(e) and e.lower() not in seen_contacts]

            html = fetch_page(url, session)
            if not html:
                continue

            page_emails = [e for e in EMAIL_REGEX.findall(html)
                           if is_valid_email(e) and e.lower() not in seen_contacts]
            all_emails = list(set(page_emails + snippet_emails))

            pids = list(dict.fromkeys(re.findall(r"open\.spotify\.com/playlist/([a-zA-Z0-9]{22})", html)))
            new_pids = [p for p in pids if p not in seen_ids]

            if not all_emails and not new_pids:
                continue

            print(f"  {url[:70]}... ({len(all_emails)} new emails, {len(new_pids)} new playlists)")

            # Process playlists
            for pid in new_pids[:20]:
                if len(all_rows) >= target:
                    break
                seen_ids.add(pid)
                data = get_playlist_data(session, token_mgr, pid)
                if not data or data["editorial"]:
                    continue
                merged = list(set(data["emails"]))
                if not merged:
                    continue
                email_str = ", ".join(merged[:3])
                if email_str.lower() in seen_contacts:
                    continue
                seen_contacts.add(email_str.lower())
                for e in merged: seen_contacts.add(e.lower())
                row = {
                    "email": email_str, "instagram": "",
                    "playlist_name": data["name"],
                    "playlist_url": f"https://open.spotify.com/playlist/{pid}",
                    "keyword": "Spreadsheet",
                    "description_snippet": data["description"][:100].replace("\n", " ") if data["description"] else "",
                    "followers": "", "priority": "",
                }
                all_rows.append(row)
                total_new += 1
                print(f"    HIT: {data['name'][:40]} | {email_str}")
                time.sleep(0.3)

            # Add standalone emails
            for email in all_emails:
                if len(all_rows) >= target:
                    break
                if email.lower() in seen_contacts:
                    continue
                seen_contacts.add(email.lower())
                from urllib.parse import urlparse
                row = {
                    "email": email, "instagram": "",
                    "playlist_name": "", "playlist_url": "",
                    "keyword": "Spreadsheet",
                    "description_snippet": f"From {urlparse(url).netloc}",
                    "followers": "", "priority": "",
                }
                all_rows.append(row)
                total_new += 1
                print(f"    + {email}")

            if total_new > 0 and total_new % 10 == 0:
                save_csv(all_rows)

            time.sleep(random.uniform(1, 3))

        time.sleep(random.uniform(8, 15))

    save_csv(all_rows)
    print(f"\nPhase 1 done: +{total_new} | Total: {len(all_rows)}")

    # ── Phase 2: Scrape indiemono.com playlists ──
    if len(all_rows) < target:
        print(f"\n{'=' * 60}")
        print("PHASE 2: Scraping indiemono.com playlists...")
        print(f"{'=' * 60}")

        # Indiemono had 157 playlists on their player page
        indiemono_url = "https://player.indiemono.com/"
        html = fetch_page(indiemono_url, session)
        pids = list(dict.fromkeys(re.findall(r"open\.spotify\.com/playlist/([a-zA-Z0-9]{22})", html)))
        # Also try the format they might use
        pids += list(dict.fromkeys(re.findall(r"spotify:playlist:([a-zA-Z0-9]{22})", html)))
        pids = list(dict.fromkeys(pids))
        new_pids = [p for p in pids if p not in seen_ids]
        print(f"  Found {len(pids)} playlists ({len(new_pids)} new) on indiemono")

        phase2_new = 0
        for pid in new_pids:
            if len(all_rows) >= target:
                break
            seen_ids.add(pid)
            data = get_playlist_data(session, token_mgr, pid)
            if not data or data["editorial"]:
                continue
            if not data["emails"]:
                continue
            email_str = ", ".join(data["emails"][:3])
            if email_str.lower() in seen_contacts:
                continue
            seen_contacts.add(email_str.lower())
            row = {
                "email": email_str, "instagram": "",
                "playlist_name": data["name"],
                "playlist_url": f"https://open.spotify.com/playlist/{pid}",
                "keyword": "Indiemono",
                "description_snippet": data["description"][:100].replace("\n", " ") if data["description"] else "",
                "followers": "", "priority": "",
            }
            all_rows.append(row)
            total_new += 1
            phase2_new += 1
            print(f"    HIT: {data['name'][:40]} | {email_str}")
            time.sleep(0.3)

            if phase2_new % 10 == 0:
                save_csv(all_rows)
                token_mgr.refresh()

        # Also try indiemono playlist pages
        for page_path in [
            "/playlist/undiscovered-brilliant-playli",
            "/playlist/groovy-vibes-2/",
            "/playlist/love-songs-playlist/",
            "/playlist/oldies-motivation-playlist/",
        ]:
            if len(all_rows) >= target:
                break
            url = f"https://indiemono.com{page_path}"
            html = fetch_page(url, session)
            if not html:
                continue
            pids = list(dict.fromkeys(re.findall(r"open\.spotify\.com/playlist/([a-zA-Z0-9]{22})", html)))
            new_pids = [p for p in pids if p not in seen_ids]
            for pid in new_pids:
                if len(all_rows) >= target:
                    break
                seen_ids.add(pid)
                data = get_playlist_data(session, token_mgr, pid)
                if not data or data["editorial"] or not data["emails"]:
                    continue
                email_str = ", ".join(data["emails"][:3])
                if email_str.lower() in seen_contacts:
                    continue
                seen_contacts.add(email_str.lower())
                row = {
                    "email": email_str, "instagram": "",
                    "playlist_name": data["name"],
                    "playlist_url": f"https://open.spotify.com/playlist/{pid}",
                    "keyword": "Indiemono",
                    "description_snippet": data["description"][:100].replace("\n", " ") if data["description"] else "",
                    "followers": "", "priority": "",
                }
                all_rows.append(row)
                total_new += 1
                phase2_new += 1
                print(f"    HIT: {data['name'][:40]} | {email_str}")
                time.sleep(0.3)

        save_csv(all_rows)
        print(f"\nPhase 2 done: +{phase2_new} | Total: {len(all_rows)}")

    # ── Phase 3: More DDG with different query patterns targeting email-rich pages ──
    if len(all_rows) < target:
        print(f"\n{'=' * 60}")
        print("PHASE 3: More targeted web searches...")
        print(f"{'=' * 60}")

        more_queries = [
            "\"playlist curators\" \"@gmail.com\" contact submit",
            "\"spotify playlist\" \"@gmail.com\" \"submit\" -submithub",
            "\"spotify curator\" \"@gmail.com\" hip hop",
            "\"spotify curator\" \"@gmail.com\" lofi",
            "\"spotify curator\" \"@gmail.com\" R&B",
            "\"spotify curator\" \"@hotmail.com\" submit",
            "\"spotify curator\" \"@yahoo.com\" submit",
            "\"playlist submission\" \"@gmail\" list contacts",
            "\"curator email\" spotify playlist list free 2024",
            "\"curator email\" spotify playlist list free 2025",
            "\"music submission\" contacts email list indie",
            "\"music submission\" contacts email list hip hop",
            "\"music blog\" email submit contact list",
            "\"music press\" email contact list indie",
            "\"music PR\" contact list email free",
            "\"A&R\" email contact list free",
            "\"A&R\" contact email music submission",
            "\"record label\" email contact list indie",
            "\"record label\" A&R email submission list",
            "\"music supervisor\" email contact list",
        ]

        phase3_new = 0
        for q in more_queries:
            if len(all_rows) >= target:
                break
            print(f"\n  {q[:65]}...")
            try:
                with DDGS() as ddgs:
                    results = ddgs.text(q, max_results=15)
            except Exception as e:
                if "Ratelimit" in str(e):
                    time.sleep(60)
                continue

            for r in results:
                url = r.get("href", "") or ""
                if not url or url in scraped_urls:
                    continue
                scraped_urls.add(url)
                if "spotify.com" in url:
                    continue

                html = fetch_page(url, session)
                if not html:
                    continue

                new_emails = [e for e in EMAIL_REGEX.findall(html)
                              if is_valid_email(e) and e.lower() not in seen_contacts]
                if not new_emails:
                    continue

                print(f"    {url[:60]}... ({len(new_emails)} new emails)")
                for email in new_emails:
                    if len(all_rows) >= target:
                        break
                    if email.lower() in seen_contacts:
                        continue
                    seen_contacts.add(email.lower())
                    from urllib.parse import urlparse
                    row = {
                        "email": email, "instagram": "",
                        "playlist_name": "", "playlist_url": "",
                        "keyword": "Web Search",
                        "description_snippet": f"From {urlparse(url).netloc}",
                        "followers": "", "priority": "",
                    }
                    all_rows.append(row)
                    total_new += 1
                    phase3_new += 1
                    print(f"      + {email}")

                if phase3_new > 0 and phase3_new % 10 == 0:
                    save_csv(all_rows)
                time.sleep(random.uniform(1, 3))

            time.sleep(random.uniform(8, 15))

        save_csv(all_rows)
        print(f"\nPhase 3 done: +{phase3_new} | Total: {len(all_rows)}")

    count = save_csv(all_rows)
    print(f"\n{'=' * 60}")
    print(f"FINAL: +{total_new} new. {count} total in output.csv")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
