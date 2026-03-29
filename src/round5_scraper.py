"""Round 5 scraper - find 200 more contacts.

Fresh search angles: different query patterns, deeper pagination on
known-good sources, and new curator directory pages.
"""

import csv
import re
import time
import random
from urllib.parse import urlparse

import requests
import urllib3
from ddgs import DDGS

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
IG_REGEX = re.compile(
    r"(?:instagram\.com/|(?:^|[\s|•·\-,])(?:ig|insta(?:gram)?)[:\s/@]+@?)([a-zA-Z0-9][a-zA-Z0-9_.]{2,29})",
    re.IGNORECASE | re.MULTILINE,
)
IG_STOP = {
    "for","the","and","this","that","with","from","not","are","was",
    "but","has","had","have","will","can","all","her","his","its",
    "our","you","com","org","net","www","http","https",
    "reel","reels","explore","stories","p",
}
JUNK_DOMAINS = {
    "spotify.com","submithub.com","example.com","w3.org","schema.org",
    "googleapis.com","google.com","facebook.com","twitter.com","youtube.com",
    "apple.com","sentry.io","blogger.com","wordpress.com","wordpress.org",
    "gravatar.com","cloudflare.com","yandex.ru","mail.ru","wixpress.com",
    "sentry-next.wixpress.com","playlistpush.com","wp.com","cdn.com",
    "microsoft.com","amazon.com","sentry.rnd.infrapu.sh",
}
JUNK_EMAILS = {
    "example@gmail.com","email@example.com","your@email.com",
    "youremail@gmail.com","name@email.com","test@test.com",
    "noreply@spotify.com","info@submithub.com","noreply@blogger.com",
    "example@domain.com","john@doe.com",
}

TOKEN_PLAYLISTS = [
    "37i9dQZF1DXcBWIGoYBM5M","37i9dQZF1DX0XUsuxWHRQd",
    "37i9dQZF1DWXRqgorJj26U",
]
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]
FIELDNAMES = ["email","instagram","playlist_name","playlist_url","keyword",
              "description_snippet","followers","priority"]


def valid_email(e):
    el = e.lower().strip()
    if el in JUNK_EMAILS:
        return False
    domain = el.split("@")[-1] if "@" in el else ""
    if domain in JUNK_DOMAINS or any(domain.endswith(f".{j}") for j in JUNK_DOMAINS):
        return False
    if len(e) < 6:
        return False
    if e.endswith((".png",".jpg",".svg",".gif",".css",".js",".ico",".webp")):
        return False
    tld = domain.split(".")[-1] if "." in domain else ""
    if len(tld) < 2 or len(tld) > 10:
        return False
    local = el.split("@")[0]
    if len(local) > 20 and all(c in "0123456789abcdef-" for c in local):
        return False
    if "example" in el or "your@" in el or "u002f" in el:
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
        for pid in TOKEN_PLAYLISTS:
            self.session.headers["User-Agent"] = random.choice(USER_AGENTS)
            try:
                resp = self.session.get(
                    f"https://open.spotify.com/embed/playlist/{pid}", timeout=15)
                tokens = re.findall(r'"accessToken":"([^"]+)"', resp.text)
                if tokens:
                    self.token = tokens[0]
                    return self.token
            except Exception:
                continue
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
                name = s.strip()
                continue
            if len(s) >= 10 and not desc:
                desc = s.strip()
                break
        emails = [e for e in EMAIL_REGEX.findall(text) if valid_email(e)]
        raw_ig = IG_REGEX.findall(text)
        igs = [h for h in raw_ig if h.lower() not in IG_STOP and len(h) > 2]
        editorial = any(m in text.lower() for m in ["spotify:user:spotify","isalgotorial"])
        return {"name": name, "description": desc, "emails": list(set(emails)),
                "instagrams": list(set(igs)), "editorial": editorial}
    except Exception:
        return None


def scrape_page(url, session):
    try:
        resp = session.get(url, timeout=20, headers={
            "User-Agent": random.choice(USER_AGENTS), "Accept": "text/html,*/*",
        }, allow_redirects=True)
        if resp.status_code != 200 or len(resp.text) < 100:
            return [], [], []
        text = resp.text
        emails = [e for e in EMAIL_REGEX.findall(text) if valid_email(e)]
        pids = list(dict.fromkeys(re.findall(
            r"open\.spotify\.com/playlist/([a-zA-Z0-9]{22})", text)))
        base = urlparse(url)
        links = []
        for m in re.finditer(r'href="([^"]*)"', text):
            href = m.group(1)
            if href.startswith("/") and not href.startswith("//"):
                links.append(f"{base.scheme}://{base.netloc}{href}")
            elif href.startswith(f"{base.scheme}://{base.netloc}"):
                links.append(href)
        return emails, pids, links[:25]
    except Exception:
        return [], [], []


def load_existing(filename="output.csv"):
    rows, seen_contacts, seen_ids = [], set(), set()
    try:
        with open(filename, "r", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                for k in ("followers","priority"):
                    if k not in row:
                        row[k] = ""
                rows.append(row)
                url = row.get("playlist_url","")
                if "/playlist/" in url:
                    seen_ids.add(url.split("/playlist/")[-1].split("?")[0])
                for e in row.get("email","").split(","):
                    if e.strip(): seen_contacts.add(e.strip().lower())
                for i in row.get("instagram","").split(","):
                    if i.strip(): seen_contacts.add(i.strip().lower())
    except FileNotFoundError:
        pass
    return rows, seen_contacts, seen_ids


def save_csv(rows, filename="output.csv"):
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def add_row(all_rows, seen_contacts, email_str, ig_str, name, pid, keyword, desc):
    key = (email_str or ig_str).lower()
    if key in seen_contacts:
        return False
    seen_contacts.add(key)
    if email_str:
        for e in email_str.split(","):
            seen_contacts.add(e.strip().lower())
    all_rows.append({
        "email": email_str, "instagram": ig_str,
        "playlist_name": name,
        "playlist_url": f"https://open.spotify.com/playlist/{pid}" if pid else "",
        "keyword": keyword[:50],
        "description_snippet": desc[:100].replace("\n"," ") if desc else "",
        "followers": "", "priority": "high" if pid else "",
    })
    return True


def main():
    target_new = 200
    existing_rows, seen_contacts, seen_ids = load_existing()
    print(f"Loaded {len(existing_rows)} existing | Target: +{target_new}\n")

    session = requests.Session()
    session.verify = False
    token_mgr = TokenManager()
    if not token_mgr.get_token():
        print("ERROR: No token")
        return
    print("Token ready.\n")

    all_rows = list(existing_rows)
    total_new = 0
    scraped_urls = set()

    # ── PHASE 1: Deep Telegram pagination (high playlist density) ──
    print("=== PHASE 1: Telegram deep scrape ===")
    tg_pages = [f"https://t.me/s/spotifypls?before={n}" for n in range(3500, 1000, -200)]
    tg_pages += [f"https://t.me/s/spotifypls?before={n}" for n in range(7000, 6700, -50)]
    tg_pages += [
        "https://t.me/s/playlistsubmissions",
        "https://t.me/s/playlistsubmissions?before=500",
        "https://t.me/s/spotifysubmit",
        "https://t.me/s/spotifysubmit?before=500",
    ]

    for url in tg_pages:
        if total_new >= target_new * 0.4:  # Cap phase 1 at 40%
            break
        print(f"  TG: {url[-40:]} (new: {total_new})")
        try:
            resp = session.get(url, timeout=20, headers={
                "User-Agent": random.choice(USER_AGENTS)})
            if resp.status_code != 200:
                continue
            pids = [p for p in dict.fromkeys(re.findall(
                r"open\.spotify\.com/playlist/([a-zA-Z0-9]{22})", resp.text))
                if p not in seen_ids]
            for pid in pids:
                if total_new >= target_new * 0.4:
                    break
                seen_ids.add(pid)
                data = get_playlist_data(session, token_mgr, pid)
                if not data or data["editorial"]:
                    continue
                if not data["emails"] and not data["instagrams"]:
                    continue
                email_str = ", ".join(data["emails"][:3])
                ig_str = ", ".join(data["instagrams"][:3])
                if add_row(all_rows, seen_contacts, email_str, ig_str,
                          data["name"], pid, "Telegram Deep", data["description"]):
                    total_new += 1
                    print(f"    HIT: {data['name'][:35]} | {email_str or ig_str}")
                time.sleep(random.uniform(0.2, 0.5))
        except Exception as e:
            print(f"    Error: {e}")
        time.sleep(random.uniform(2, 4))

    if total_new > 0:
        save_csv(all_rows)
        print(f"  [SAVED] {len(all_rows)} total after Phase 1 (+{total_new})\n")

    # ── PHASE 2: DDG search with fresh query patterns ──
    print("=== PHASE 2: Fresh DDG searches ===")
    search_queries = [
        # Different patterns than before
        "spotify playlist @gmail.com submit rap 2026",
        "spotify playlist @gmail.com submit R&B 2026",
        "spotify playlist @gmail.com submit lofi 2026",
        "spotify playlist @gmail.com hip hop curator",
        "spotify playlist @hotmail.com submit music",
        "spotify playlist @outlook.com submit music",
        "spotify curator email submit music free 2026",
        "spotify curator email indie pop soul 2026",
        "spotify curator free list email rap R&B lofi 2026",
        "free spotify playlist curator contacts hip hop 2026",
        "independent spotify playlist accept submissions email",
        "submit music spotify playlist curators free 2026",

        # Music blog / promotion sites
        "music blog spotify playlist email submit hip hop 2026",
        "music blog spotify curators email list 2026",
        "music promotion spotify playlist curators free 2026",
        "promote your music spotify playlist email curators",
        "how to get on spotify playlists email curators 2026",
        "best way to submit music to spotify playlists email",

        # Submission sites
        "site:letssubmit.com rap",
        "site:letssubmit.com R&B",
        "site:letssubmit.com lofi",
        "site:letssubmit.com hip hop",
        "site:letssubmit.com pop",
        "site:curatorclub.com rap",
        "site:curatorclub.com R&B",
        "site:curatorclub.com lofi",
        "site:groover.co playlist hip hop",
        "site:groover.co playlist R&B",
        "site:playlistsubmit.com indie",
        "site:playlistsubmit.com lofi",
        "site:playlistsubmit.com soul",
        "site:playlistsubmit.com electronic",
        "site:playlistsubmit.com pop",
        "site:playlistsubmit.com trap",

        # Niche genre searches
        "afro house spotify playlist curator email",
        "tech house spotify playlist submit email",
        "deep house spotify playlist curator email",
        "minimal techno spotify playlist submit email",
        "hardstyle spotify playlist curator email",
        "drum and bass spotify playlist submit email",
        "dubstep spotify playlist curator email submit",
        "trance spotify playlist submit email curator",
        "garage rock spotify playlist email",
        "math rock spotify playlist submit email",
        "post punk spotify playlist curator email",
        "shoegaze spotify playlist submit email",
        "dream pop spotify playlist curator email",
        "noise pop spotify playlist submit email",
        "slowcore spotify playlist curator email",
        "midwest emo spotify playlist submit email",
        "screamo spotify playlist curator email",
        "post rock spotify playlist submit email",
        "stoner rock spotify playlist curator email",
        "psych rock spotify playlist submit email",
        "surf rock spotify playlist curator email",
        "ska punk spotify playlist submit email",
        "gothic rock spotify playlist curator email",
        "industrial spotify playlist submit email",
        "new wave spotify playlist curator email",
        "darkwave spotify playlist submit email",
        "witch house spotify playlist curator email",
        "folktronica spotify playlist submit email",
        "indietronica spotify playlist curator email",
        "future garage spotify playlist submit email",
        "uk bass spotify playlist curator email",
        "gqom spotify playlist submit email",
        "kuduro spotify playlist curator email",
        "cumbia spotify playlist submit email",
        "bossa nova spotify playlist curator email",
        "city pop spotify playlist submit email 2026",
        "future funk spotify playlist curator email 2026",
        "lo-fi house spotify playlist submit email",
        "broken beat spotify playlist curator email",
        "nu jazz spotify playlist submit email",
        "acid jazz spotify playlist curator email",
        "progressive house spotify playlist email submit",
        "melodic house spotify playlist curator email",
        "organic house spotify playlist submit email",
        "afro tech spotify playlist curator email",

        # More submission patterns
        "spotify playlist \"submit here\" email rap",
        "spotify playlist \"send tracks\" email curator",
        "spotify playlist \"submission form\" email contact",
        "spotify playlist \"looking for music\" email",
        "spotify curator \"email us\" playlist rap",
        "spotify curator playlist \"new music\" email 2026",
        "spotify playlist curators accepting demos email",
        "spotify playlist accept new artists email 2026",
    ]

    for qi, query in enumerate(search_queries):
        if total_new >= target_new:
            break
        print(f"\n[{qi+1}/{len(search_queries)}] {query[:60]}... (new: {total_new}/{target_new})")

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
            if total_new >= target_new:
                break
            url = r.get("href","") or r.get("link","")
            if not url or url in scraped_urls:
                continue
            if "spotify.com" in url and "open.spotify.com/playlist" not in url:
                continue
            scraped_urls.add(url)

            # Direct playlist URL
            pid_match = re.search(r"open\.spotify\.com/playlist/([a-zA-Z0-9]{22})", url)
            if pid_match:
                pid = pid_match.group(1)
                if pid in seen_ids:
                    continue
                seen_ids.add(pid)
                data = get_playlist_data(session, token_mgr, pid)
                if data and not data["editorial"] and (data["emails"] or data["instagrams"]):
                    email_str = ", ".join(data["emails"][:3])
                    ig_str = ", ".join(data["instagrams"][:3])
                    if add_row(all_rows, seen_contacts, email_str, ig_str,
                              data["name"], pid, query, data["description"]):
                        total_new += 1
                        print(f"    HIT [DIRECT]: {data['name'][:35]} | {email_str or ig_str}")
                time.sleep(random.uniform(0.3, 0.6))
                continue

            # Scrape page
            page_emails, page_pids, internal_links = scrape_page(url, session)
            new_emails = [e for e in page_emails if e.lower() not in seen_contacts]
            new_pids = [p for p in page_pids if p not in seen_ids]

            snippet = r.get("body","") or ""
            snippet_emails = [e for e in EMAIL_REGEX.findall(snippet)
                             if valid_email(e) and e.lower() not in seen_contacts]
            all_emails = list(set(new_emails + snippet_emails))

            if not all_emails and not new_pids:
                continue

            print(f"  {url[:65]}...")
            print(f"  Found {len(all_emails)} emails, {len(new_pids)} playlists")

            # Pair emails with playlists
            if new_pids:
                for pid in new_pids[:20]:
                    if total_new >= target_new:
                        break
                    seen_ids.add(pid)
                    data = get_playlist_data(session, token_mgr, pid)
                    if not data or data["editorial"]:
                        continue
                    merged = list(set(data["emails"] + all_emails[:3]))
                    merged = [e for e in merged if valid_email(e)]
                    igs = data["instagrams"]
                    if not merged and not igs:
                        continue
                    email_str = ", ".join(merged[:3])
                    ig_str = ", ".join(igs[:3])
                    if add_row(all_rows, seen_contacts, email_str, ig_str,
                              data["name"], pid, query, data["description"]):
                        total_new += 1
                        print(f"    HIT: {data['name'][:35]} | {email_str or ig_str}")
                    time.sleep(random.uniform(0.2, 0.5))

            # Standalone emails
            for email in all_emails[:5]:
                if total_new >= target_new:
                    break
                if email.lower() in seen_contacts:
                    continue
                seen_contacts.add(email.lower())
                all_rows.append({
                    "email": email, "instagram": "",
                    "playlist_name": "", "playlist_url": "",
                    "keyword": query[:50],
                    "description_snippet": f"Found on {urlparse(url).netloc}",
                    "followers": "", "priority": "",
                })
                total_new += 1
                print(f"    + {email}")

            # Follow internal links
            for link in internal_links[:5]:
                if link in scraped_urls or total_new >= target_new:
                    continue
                if not any(kw in link.lower() for kw in [
                    "curator","playlist","submit","contact","email","music",
                    "genre","rap","hip-hop","r-b","lofi","pop","soul"]):
                    continue
                scraped_urls.add(link)
                sub_emails, sub_pids, _ = scrape_page(link, session)
                new_sub = [e for e in sub_emails if valid_email(e) and e.lower() not in seen_contacts]
                new_sub_pids = [p for p in sub_pids if p not in seen_ids]

                if new_sub_pids:
                    for pid in new_sub_pids[:10]:
                        if total_new >= target_new:
                            break
                        seen_ids.add(pid)
                        data = get_playlist_data(session, token_mgr, pid)
                        if not data or data["editorial"]:
                            continue
                        merged = list(set(data["emails"] + new_sub[:3]))
                        merged = [e for e in merged if valid_email(e)]
                        igs = data["instagrams"]
                        if not merged and not igs:
                            continue
                        email_str = ", ".join(merged[:3])
                        ig_str = ", ".join(igs[:3])
                        if add_row(all_rows, seen_contacts, email_str, ig_str,
                                  data["name"], pid, query, data["description"]):
                            total_new += 1
                            print(f"    HIT [SUB]: {data['name'][:35]} | {email_str or ig_str}")
                        time.sleep(random.uniform(0.2, 0.5))
                elif new_sub:
                    for email in new_sub[:3]:
                        if total_new >= target_new:
                            break
                        if email.lower() in seen_contacts:
                            continue
                        seen_contacts.add(email.lower())
                        all_rows.append({
                            "email": email, "instagram": "",
                            "playlist_name": "", "playlist_url": "",
                            "keyword": query[:50],
                            "description_snippet": f"Found on {urlparse(link).netloc}",
                            "followers": "", "priority": "",
                        })
                        total_new += 1
                        print(f"    + {email} (sub)")
                time.sleep(1)

            if total_new > 0 and total_new % 15 == 0:
                save_csv(all_rows)
                print(f"  [SAVED] {len(all_rows)} total")

        time.sleep(random.uniform(8, 15))

    # ── PHASE 3: PlaylistLookup deep pagination ──
    if total_new < target_new:
        print(f"\n=== PHASE 3: PlaylistLookup deep scrape (need {target_new - total_new} more) ===")
        pl_genres = [
            "hip-hop","r-and-b","pop","indie","electronic","rock","soul",
            "jazz","folk","country","metal","punk","reggae","latin",
            "classical","ambient","blues","gospel","world","dancehall",
        ]
        for genre in pl_genres:
            if total_new >= target_new:
                break
            url = f"https://www.playlistlookup.com/genre/{genre}"
            if url in scraped_urls:
                continue
            scraped_urls.add(url)
            print(f"  PLLookup: {genre} (new: {total_new})")
            _, pids, links = scrape_page(url, session)
            new_pids = [p for p in pids if p not in seen_ids]
            for pid in new_pids:
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
                if add_row(all_rows, seen_contacts, email_str, ig_str,
                          data["name"], pid, f"PlaylistLookup/{genre}",
                          data["description"]):
                    total_new += 1
                    print(f"    HIT: {data['name'][:35]} | {email_str or ig_str}")
                time.sleep(random.uniform(0.2, 0.5))
            # Follow subpages
            for link in links[:10]:
                if link in scraped_urls or total_new >= target_new:
                    continue
                if "genre" not in link and "playlist" not in link:
                    continue
                scraped_urls.add(link)
                _, sub_pids, _ = scrape_page(link, session)
                for pid in [p for p in sub_pids if p not in seen_ids][:10]:
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
                    if add_row(all_rows, seen_contacts, email_str, ig_str,
                              data["name"], pid, f"PlaylistLookup/{genre}",
                              data["description"]):
                        total_new += 1
                        print(f"    HIT [sub]: {data['name'][:35]} | {email_str or ig_str}")
                    time.sleep(random.uniform(0.2, 0.5))
                time.sleep(1)
            time.sleep(random.uniform(3, 5))

    # Final save
    count = save_csv(all_rows)
    print(f"\n{'='*60}")
    print(f"DONE! +{total_new} new contacts. {count} total in output.csv")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
