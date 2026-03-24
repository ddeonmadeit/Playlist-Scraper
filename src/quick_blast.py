"""Quick blast scraper - high-yield focused parallel approach.

Targets the highest-yield search patterns and scrapes aggressively.
Uses multiple DDG query batches with proven email-finding patterns.
"""

import csv
import os
import re
import sys
import time
import random
from datetime import datetime

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
EMAIL_BLACKLIST = {
    "abuse@spotify.com", "support@spotify.com", "copyright@spotify.com",
    "privacy@spotify.com", "legal@spotify.com", "info@spotify.com",
    "example@gmail.com", "email@example.com", "your@email.com",
    "youremail@gmail.com", "name@email.com",
}

TOKEN_PLAYLISTS = [
    "37i9dQZF1DXcBWIGoYBM5M", "37i9dQZF1DX0XUsuxWHRQd",
    "37i9dQZF1DWXRqgorJj26U", "37i9dQZF1DX4sWSpwq3LiO",
]
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]
FIELDNAMES = ["email", "instagram", "playlist_name", "playlist_url", "keyword",
              "description_snippet", "followers", "priority"]


class TokenManager:
    def __init__(self):
        self.token = None
        self.session = requests.Session()
        self.session.verify = False

    def get_token(self):
        if self.token:
            return self.token
        return self.refresh()

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


def extract_contacts(text):
    if not text:
        return [], []
    emails = EMAIL_REGEX.findall(text)
    emails = [e for e in emails if e.lower() not in EMAIL_BLACKLIST
              and not e.endswith((".png", ".jpg", ".svg", ".gif", ".css", ".js"))
              and len(e) > 5]
    raw_ig = INSTAGRAM_REGEX.findall(text)
    instagrams = [h for h in raw_ig if h.lower() not in IG_STOPWORDS and len(h) > 2]
    return list(set(emails)), list(set(instagrams))


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
        name = ""
        description = ""
        for s in strings:
            if len(s) >= 3 and not name:
                name = s.strip()
                continue
            if len(s) >= 10 and not description:
                description = s.strip()
                break
        emails, instagrams = extract_contacts(text)
        is_editorial = any(m in text.lower() for m in ["spotify:user:spotify", "isalgotorial"])
        return {"name": name, "description": description, "emails": emails,
                "instagrams": instagrams, "editorial": is_editorial}
    except Exception:
        return None


def ddg_search(query, max_results=50):
    playlist_ids = []
    try:
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=max_results)
            for r in results:
                for text in [r.get("href", ""), r.get("body", ""), r.get("title", "")]:
                    for m in re.finditer(r"open\.spotify\.com/playlist/([a-zA-Z0-9]{22})", text):
                        playlist_ids.append(m.group(1))
    except Exception as e:
        if "Ratelimit" in str(e) or "403" in str(e):
            time.sleep(45)
        else:
            time.sleep(5)
    return list(dict.fromkeys(playlist_ids))


def ddg_search_emails_directly(query, max_results=20):
    """Search DDG for pages containing curator emails directly from snippets."""
    contacts = []
    try:
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=max_results)
            for r in results:
                body = r.get("body", "") or r.get("snippet", "")
                title = r.get("title", "")
                full_text = f"{title} {body}"
                emails, igs = extract_contacts(full_text)
                # Also check for Spotify playlist URLs in the same result
                pids = re.findall(r"open\.spotify\.com/playlist/([a-zA-Z0-9]{22})",
                                  r.get("href", "") + " " + body)
                if emails or igs:
                    contacts.append({
                        "emails": emails, "instagrams": igs,
                        "playlist_ids": list(set(pids)),
                        "source": body[:100]
                    })
    except Exception:
        time.sleep(10)
    return contacts


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

    if len(existing_rows) >= target:
        print("Already at target!")
        return

    session = requests.Session()
    session.verify = False
    session.headers.update({"User-Agent": random.choice(USER_AGENTS)})

    token_mgr = TokenManager()
    if not token_mgr.get_token():
        print("ERROR: No token")
        return
    print("Token ready.\n")

    all_rows = list(existing_rows)
    total_new = 0

    # ── Direct email harvesting from web pages about curators ──
    print("=== PHASE 1: Direct email harvesting from curator pages ===\n")

    # Search for pages that list curator emails
    harvest_queries = [
        "spotify playlist curator email gmail.com hip hop",
        "spotify playlist curator email gmail.com lofi",
        "spotify playlist curator email gmail.com R&B",
        "spotify playlist curator email gmail.com rap",
        "spotify playlist curator email gmail.com soul",
        "spotify playlist curator email gmail.com indie",
        "spotify playlist curators contact list 2024",
        "spotify playlist curators contact list 2025",
        "free spotify playlist submission email list",
        "spotify curator email list hip hop rap lofi",
        "submit music spotify playlist free email contact",
        "spotify playlist submission free no submithub email",
        "independent spotify playlist curators email",
        "underground hip hop spotify playlist curators",
        "lofi chill hop playlist curators email list",
        "R&B neo soul playlist curators email free",
    ]

    harvested_emails = set()
    for q in harvest_queries:
        if len(all_rows) >= target:
            break
        print(f"  Harvesting: {q[:60]}...")
        try:
            with DDGS() as ddgs:
                results = ddgs.text(q, max_results=20)
                for r in results:
                    body = r.get("body", "") or ""
                    title = r.get("title", "") or ""
                    href = r.get("href", "") or ""
                    full = f"{title} {body}"
                    emails = EMAIL_REGEX.findall(full)
                    emails = [e for e in emails if e.lower() not in EMAIL_BLACKLIST
                              and not e.endswith((".png", ".jpg", ".svg", ".gif"))
                              and e.lower() not in seen_contacts]
                    for email in emails:
                        harvested_emails.add(email)
        except Exception:
            time.sleep(10)
        time.sleep(random.uniform(8, 15))

    # Add harvested emails as contacts (without playlist links for now)
    if harvested_emails:
        print(f"\n  Found {len(harvested_emails)} unique emails from web pages")
        for email in sorted(harvested_emails):
            if email.lower() in seen_contacts:
                continue
            seen_contacts.add(email.lower())
            row = {
                "email": email,
                "instagram": "",
                "playlist_name": "",
                "playlist_url": "",
                "keyword": "Web Harvest",
                "description_snippet": "Curator email found via web search",
                "followers": "",
                "priority": "",
            }
            all_rows.append(row)
            total_new += 1
            print(f"    + {email}")

        save_csv(all_rows)
        print(f"\n  Phase 1 done: +{total_new} | Total: {len(all_rows)}\n")

    # ── Phase 2: Aggressive DDG playlist search with new patterns ──
    print("=== PHASE 2: Fresh DDG playlist searches ===\n")

    # High-yield playlist search queries
    genres = [
        "phonk", "drill", "UK drill", "afrobeats", "amapiano", "grime",
        "cloud rap", "emo rap", "trip hop", "downtempo", "vaporwave",
        "future bass", "trap soul", "melodic rap", "pluggnb",
        "anime lofi", "gaming music", "coding beats", "dark trap",
        "90s hip hop", "2000s rap", "golden age hip hop",
        "abstract hip hop", "instrumental hip hop", "jazz rap fusion",
        "smooth R&B jams", "classic soul music", "funk playlist",
        "G-funk west coast", "UK rap grime", "French rap",
        "German rap", "Latin trap", "reggaeton", "dancehall",
        "city pop", "K-R&B Korean", "Japanese hip hop",
        "worship music", "gospel hip hop", "christian rap",
        "motivational rap", "positive hip hop",
        "female rapper playlist", "female R&B playlist",
        "throwback R&B", "throwback hip hop", "90s R&B playlist",
        "summer hits playlist", "fall vibes playlist",
        "winter chill playlist", "spring playlist",
        "midnight vibes", "3am playlist", "late night drives",
        "sad rap", "sad R&B", "heartbreak playlist",
        "breakup songs hip hop", "love songs R&B",
        "new music discovery", "fresh finds indie",
    ]

    queries = []
    for g in genres:
        queries.append((f"site:open.spotify.com/playlist {g} submit email", g))
        queries.append((f"site:open.spotify.com/playlist {g}", g))

    # Add proven high-yield patterns with different terms
    extra = [
        "site:open.spotify.com/playlist submissions open email @gmail",
        "site:open.spotify.com/playlist send demos email contact",
        "site:open.spotify.com/playlist \"submit your\" music playlist",
        "site:open.spotify.com/playlist \"send your track\" playlist",
        "site:open.spotify.com/playlist \"DM to submit\" playlist",
        "site:open.spotify.com/playlist \"accepting demos\" playlist",
        "site:open.spotify.com/playlist free promotion submit",
        "site:open.spotify.com/playlist \"playlist submission\" contact",
        "site:open.spotify.com/playlist curator blog submit",
        "site:open.spotify.com/playlist \"email us\" music playlist",
        "site:open.spotify.com/playlist promote unsigned artist",
        "site:open.spotify.com/playlist support independent artist",
        "site:open.spotify.com/playlist \"for artists\" submit track",
    ]
    for e in extra:
        queries.append((e, "Submit Pattern"))

    random.shuffle(queries)

    phase2_new = 0
    ddg_errors = 0

    for i, (query, label) in enumerate(queries):
        if len(all_rows) >= target:
            print(f"\nReached target of {target}!")
            break

        print(f"[{i+1}/{len(queries)}] {query[:65]}... (total: {len(all_rows)} +{total_new})")

        pids = ddg_search(query, max_results=50)
        new_pids = [p for p in pids if p not in seen_ids]
        print(f"  {len(pids)} found, {len(new_pids)} new")

        if not pids:
            ddg_errors += 1
            if ddg_errors >= 3:
                print("  DDG throttled, waiting 60s...")
                time.sleep(60)
                ddg_errors = 0
            continue
        ddg_errors = 0

        q_new = 0
        for pid in new_pids:
            seen_ids.add(pid)
            data = get_playlist_data(session, token_mgr, pid)
            if not data or data["editorial"]:
                continue
            if not data["emails"] and not data["instagrams"]:
                continue
            email_str = ", ".join(data["emails"][:3])
            ig_str = ", ".join(data["instagrams"][:3])
            contact_key = (email_str or ig_str).lower()
            if contact_key in seen_contacts:
                continue
            seen_contacts.add(contact_key)

            row = {
                "email": email_str,
                "instagram": ig_str,
                "playlist_name": data["name"],
                "playlist_url": f"https://open.spotify.com/playlist/{pid}",
                "keyword": label,
                "description_snippet": data["description"][:100].replace("\n", " ") if data["description"] else "",
                "followers": "",
                "priority": "",
            }
            all_rows.append(row)
            total_new += 1
            phase2_new += 1
            q_new += 1
            print(f"    HIT: {data['name'][:40]} | {email_str or ig_str}")
            time.sleep(random.uniform(0.3, 0.6))

        if q_new > 0:
            save_csv(all_rows)

        if i % 25 == 24:
            token_mgr.refresh()

        time.sleep(random.uniform(6, 12))

    count = save_csv(all_rows)
    print(f"\n{'=' * 60}")
    print(f"DONE! +{total_new} new contacts. {count} total in output.csv")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
