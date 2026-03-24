"""Deep directory scraper - crawls playlistlookup.com, artist.tools, and
similar sites that list Spotify playlists with curator contact info.
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
JUNK_DOMAINS = {
    "spotify.com", "sentry.wixpress.com", "sentry-next.wixpress.com",
    "sentry.dev.stream.tv", "w3.org", "schema.org", "googleapis.com",
    "google.com", "facebook.com", "twitter.com", "youtube.com",
    "apple.com", "microsoft.com", "amazon.com", "cloudflare.com",
    "wordpress.org", "gravatar.com", "wp.com", "wixpress.com",
    "tikfinity.com", "root-device.com", "stream.tv", "zerody.one",
    "example.com",
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
    email_lower = email.lower().strip()
    if email_lower in JUNK_EMAILS:
        return False
    domain = email_lower.split("@")[-1] if "@" in email_lower else ""
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
            if not token:
                return None
            resp = session.get(
                f"https://spclient.wg.spotify.com/playlist/v2/playlist/{playlist_id}",
                headers={"Authorization": f"Bearer {token}"}, timeout=15)
        if resp.status_code != 200:
            return None
        text = resp.content.decode("utf-8", errors="ignore")
        strings = re.findall(r"[\x20-\x7E]{3,}", text)
        name, desc = "", ""
        for s in strings:
            if len(s) >= 3 and not name:
                name = s.strip(); continue
            if len(s) >= 10 and not desc:
                desc = s.strip(); break
        emails = [e for e in EMAIL_REGEX.findall(text) if is_valid_email(e)]
        is_editorial = any(m in text.lower() for m in ["spotify:user:spotify", "isalgotorial"])
        return {"name": name, "description": desc, "emails": list(set(emails)), "editorial": is_editorial}
    except Exception:
        return None


def fetch_page(url, session):
    try:
        resp = session.get(url, timeout=20, headers={
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,*/*"
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

    # ── Playlistlookup.com genre pages ──
    print("=" * 60)
    print("Scraping playlistlookup.com genre pages...")
    print("=" * 60)

    genres = [
        "hip-hop", "r-and-b", "pop", "lo-fi", "electronic", "jazz", "soul",
        "indie", "rock", "country", "latin", "afrobeats", "dancehall",
        "reggae", "funk", "classical", "ambient", "alternative",
        "punk", "metal", "blues", "folk", "world", "gospel",
        "trap", "drill", "grime", "house", "techno", "dubstep",
        "drum-and-bass", "chill", "study", "sleep", "workout", "party",
        "sad", "happy", "love", "summer", "winter", "acoustic",
        "piano", "guitar", "beats", "instrumental",
    ]

    for genre in genres:
        if len(all_rows) >= target:
            break

        url = f"https://www.playlistlookup.com/genre/{genre}"
        print(f"\n  {url}...")
        html = fetch_page(url, session)
        if not html:
            continue

        pids = list(dict.fromkeys(re.findall(r"open\.spotify\.com/playlist/([a-zA-Z0-9]{22})", html)))
        page_emails = [e for e in EMAIL_REGEX.findall(html) if is_valid_email(e)]
        new_pids = [p for p in pids if p not in seen_ids]

        print(f"  Found {len(pids)} playlists ({len(new_pids)} new), {len(page_emails)} emails")

        hits = 0
        for pid in new_pids[:25]:
            seen_ids.add(pid)
            data = get_playlist_data(session, token_mgr, pid)
            if not data or data["editorial"]:
                continue

            merged_emails = list(set(data["emails"] + [e for e in page_emails if e.lower() not in seen_contacts]))
            if not merged_emails:
                continue

            email_str = ", ".join(merged_emails[:3])
            if email_str.lower() in seen_contacts:
                continue
            seen_contacts.add(email_str.lower())
            for e in merged_emails:
                seen_contacts.add(e.lower())

            row = {
                "email": email_str,
                "instagram": "",
                "playlist_name": data["name"],
                "playlist_url": f"https://open.spotify.com/playlist/{pid}",
                "keyword": f"PlaylistLookup/{genre}",
                "description_snippet": data["description"][:100].replace("\n", " ") if data["description"] else "",
                "followers": "",
                "priority": "",
            }
            all_rows.append(row)
            total_new += 1
            hits += 1
            print(f"    HIT: {data['name'][:40]} | {email_str}")
            time.sleep(random.uniform(0.2, 0.5))

        if hits > 0:
            save_csv(all_rows)
        time.sleep(random.uniform(2, 4))

        if total_new > 0 and total_new % 20 == 0:
            token_mgr.refresh()

    print(f"\nPlaylistLookup done: +{total_new} | Total: {len(all_rows)}")

    # ── Artist.tools genre submission pages ──
    if len(all_rows) < target:
        print(f"\n{'=' * 60}")
        print("Scraping artist.tools genre pages...")
        print(f"{'=' * 60}")

        at_genres = [
            "hip-hop", "r-and-b", "pop", "lo-fi", "electronic", "jazz",
            "soul", "indie", "rock", "latin", "afrobeats", "dancehall",
            "reggae", "funk", "ambient", "alternative", "trap",
            "chill", "study", "beats", "rap", "neo-soul",
        ]

        at_new = 0
        for genre in at_genres:
            if len(all_rows) >= target:
                break
            url = f"https://www.artist.tools/submit/{genre}"
            print(f"\n  {url}...")
            html = fetch_page(url, session)
            if not html:
                continue

            pids = list(dict.fromkeys(re.findall(r"open\.spotify\.com/playlist/([a-zA-Z0-9]{22})", html)))
            page_emails = [e for e in EMAIL_REGEX.findall(html) if is_valid_email(e)]
            new_pids = [p for p in pids if p not in seen_ids]

            print(f"  Found {len(pids)} playlists ({len(new_pids)} new), {len(page_emails)} emails")

            for pid in new_pids[:20]:
                seen_ids.add(pid)
                data = get_playlist_data(session, token_mgr, pid)
                if not data or data["editorial"]:
                    continue

                merged = list(set(data["emails"] + [e for e in page_emails if e.lower() not in seen_contacts]))
                if not merged:
                    continue

                email_str = ", ".join(merged[:3])
                if email_str.lower() in seen_contacts:
                    continue
                seen_contacts.add(email_str.lower())
                for e in merged:
                    seen_contacts.add(e.lower())

                row = {
                    "email": email_str,
                    "instagram": "",
                    "playlist_name": data["name"],
                    "playlist_url": f"https://open.spotify.com/playlist/{pid}",
                    "keyword": f"ArtistTools/{genre}",
                    "description_snippet": data["description"][:100].replace("\n", " ") if data["description"] else "",
                    "followers": "",
                    "priority": "",
                }
                all_rows.append(row)
                total_new += 1
                at_new += 1
                print(f"    HIT: {data['name'][:40]} | {email_str}")
                time.sleep(random.uniform(0.2, 0.5))

            if at_new > 0 and at_new % 5 == 0:
                save_csv(all_rows)
            time.sleep(random.uniform(2, 4))

        save_csv(all_rows)
        print(f"\nArtist.tools done: +{at_new} | Total: {len(all_rows)}")

    # ── Soundplate browse pages ──
    if len(all_rows) < target:
        print(f"\n{'=' * 60}")
        print("Scraping soundplate.com...")
        print(f"{'=' * 60}")

        sp_genres = [
            "hip-hop", "rnb", "pop", "lo-fi", "electronic", "jazz", "soul",
            "indie", "latin", "afrobeats", "dancehall", "funk", "ambient",
            "chill", "trap", "house", "techno", "rock", "country",
        ]

        sp_new = 0
        for genre in sp_genres:
            if len(all_rows) >= target:
                break
            for page in range(1, 4):
                url = f"https://play.soundplate.com/playlists?genre={genre}&page={page}"
                print(f"\n  {url}...")
                html = fetch_page(url, session)
                if not html or len(html) < 500:
                    break

                pids = list(dict.fromkeys(re.findall(r"open\.spotify\.com/playlist/([a-zA-Z0-9]{22})", html)))
                # Also try soundplate's format
                pids += list(dict.fromkeys(re.findall(r"/playlist/([a-zA-Z0-9]{22})", html)))
                pids = list(dict.fromkeys(pids))
                new_pids = [p for p in pids if p not in seen_ids]

                if not new_pids:
                    break

                print(f"  Found {len(pids)} playlists ({len(new_pids)} new)")

                for pid in new_pids[:20]:
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
                        "email": email_str,
                        "instagram": "",
                        "playlist_name": data["name"],
                        "playlist_url": f"https://open.spotify.com/playlist/{pid}",
                        "keyword": f"Soundplate/{genre}",
                        "description_snippet": data["description"][:100].replace("\n", " ") if data["description"] else "",
                        "followers": "",
                        "priority": "",
                    }
                    all_rows.append(row)
                    total_new += 1
                    sp_new += 1
                    print(f"    HIT: {data['name'][:40]} | {email_str}")
                    time.sleep(random.uniform(0.2, 0.5))

                time.sleep(random.uniform(2, 4))

        save_csv(all_rows)
        print(f"\nSoundplate done: +{sp_new} | Total: {len(all_rows)}")

    # ── DDG search for MORE directory-style pages ──
    if len(all_rows) < target:
        print(f"\n{'=' * 60}")
        print("Searching for more directory pages via DDG...")
        print(f"{'=' * 60}")

        extra_queries = [
            "site:playlistlookup.com spotify playlist",
            "site:artist.tools spotify playlist",
            "site:play.soundplate.com spotify playlist",
            "site:indiemono.com spotify playlist curator",
            "site:playlistmap.com spotify curator",
            "site:submithub.com curator profile",
            "spotify playlist curator list site:medium.com",
            "spotify playlist curator email site:notion.site",
            "spotify playlist curator list site:notion.so",
            "spotify curator list filetype:pdf",
            "spotify playlist submission free list site:docs.google.com",
        ]

        ddg_new = 0
        for q in extra_queries:
            if len(all_rows) >= target:
                break
            print(f"\n  Searching: {q[:60]}...")
            try:
                with DDGS() as ddgs:
                    results = ddgs.text(q, max_results=20)
                for r in results:
                    url = r.get("href", "") or ""
                    if not url:
                        continue
                    html = fetch_page(url, session)
                    if not html:
                        continue

                    pids = list(dict.fromkeys(re.findall(r"open\.spotify\.com/playlist/([a-zA-Z0-9]{22})", html)))
                    emails = [e for e in EMAIL_REGEX.findall(html) if is_valid_email(e)]
                    new_pids = [p for p in pids if p not in seen_ids]
                    new_emails = [e for e in emails if e.lower() not in seen_contacts]

                    if not new_pids and not new_emails:
                        continue

                    print(f"    {url[:60]}... ({len(new_pids)} new playlists, {len(new_emails)} new emails)")

                    for pid in new_pids[:15]:
                        if len(all_rows) >= target:
                            break
                        seen_ids.add(pid)
                        data = get_playlist_data(session, token_mgr, pid)
                        if not data or data["editorial"]:
                            continue
                        merged = list(set(data["emails"] + [e for e in new_emails if e.lower() not in seen_contacts]))
                        if not merged:
                            continue
                        email_str = ", ".join(merged[:3])
                        if email_str.lower() in seen_contacts:
                            continue
                        seen_contacts.add(email_str.lower())
                        for e in merged:
                            seen_contacts.add(e.lower())
                        row = {
                            "email": email_str,
                            "instagram": "",
                            "playlist_name": data["name"],
                            "playlist_url": f"https://open.spotify.com/playlist/{pid}",
                            "keyword": "DDG Directory",
                            "description_snippet": data["description"][:100].replace("\n", " ") if data["description"] else "",
                            "followers": "",
                            "priority": "",
                        }
                        all_rows.append(row)
                        total_new += 1
                        ddg_new += 1
                        print(f"      HIT: {data['name'][:40]} | {email_str}")
                        time.sleep(random.uniform(0.2, 0.5))

                    # Add standalone emails
                    for email in new_emails:
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
                            "keyword": "DDG Directory",
                            "description_snippet": f"From {urlparse(url).netloc}",
                            "followers": "",
                            "priority": "",
                        }
                        all_rows.append(row)
                        total_new += 1
                        ddg_new += 1
                        print(f"      + {email}")

                    time.sleep(random.uniform(1, 3))

            except Exception as e:
                if "Ratelimit" in str(e):
                    time.sleep(60)
                else:
                    time.sleep(5)
            time.sleep(random.uniform(8, 15))

        save_csv(all_rows)
        print(f"\nDDG directory done: +{ddg_new} | Total: {len(all_rows)}")

    count = save_csv(all_rows)
    print(f"\n{'=' * 60}")
    print(f"FINAL: +{total_new} new. {count} total in output.csv")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
