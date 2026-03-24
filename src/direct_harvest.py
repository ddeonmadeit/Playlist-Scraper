"""Direct email harvester - scrapes curator directory sites and Spotify user profiles.

Instead of searching DDG for playlist pages, this:
1. Scrapes known curator directory websites for emails + playlist links
2. Uses the wg endpoint to find Spotify user IDs from existing playlists
3. Checks user profiles for contact info
"""

import csv
import json
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
    "privacy@spotify.com", "legal@spotify.com", "info@spotify.com",
    "example@gmail.com", "email@example.com", "your@email.com",
    "youremail@gmail.com", "name@email.com", "noreply@spotify.com",
    "no-reply@spotify.com", "info@submithub.com", "hello@submithub.com",
    "support@submithub.com", "info@playlistpush.com",
}

TOKEN_PLAYLISTS = [
    "37i9dQZF1DXcBWIGoYBM5M", "37i9dQZF1DX0XUsuxWHRQd",
    "37i9dQZF1DWXRqgorJj26U", "37i9dQZF1DX4sWSpwq3LiO",
]
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
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
              and len(e) > 5 and "." in e.split("@")[-1]
              and len(e.split("@")[-1]) > 3]
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
        raw = resp.content
        text = raw.decode("utf-8", errors="ignore")
        strings = re.findall(r"[\x20-\x7E]{3,}", text)
        name = ""
        description = ""
        owner_uri = ""
        for s in strings:
            if s.startswith("spotify:user:"):
                owner_uri = s
            if len(s) >= 3 and not name:
                name = s.strip()
                continue
            if len(s) >= 10 and not description:
                description = s.strip()
                break
        emails, instagrams = extract_contacts(text)
        is_editorial = any(m in text.lower() for m in ["spotify:user:spotify", "isalgotorial"])
        return {"name": name, "description": description, "emails": emails,
                "instagrams": instagrams, "editorial": is_editorial,
                "owner_uri": owner_uri}
    except Exception:
        return None


def get_user_playlists_wg(session, token_mgr, user_id, limit=50):
    """Get a user's public playlists via internal endpoint."""
    token = token_mgr.get_token()
    if not token:
        return []
    try:
        resp = session.get(
            f"https://spclient.wg.spotify.com/user-profile-view/v3/profile/{user_id}/playlists",
            headers={"Authorization": f"Bearer {token}"},
            params={"limit": limit},
            timeout=15)
        if resp.status_code == 401:
            token_mgr.refresh()
            token = token_mgr.get_token()
            if not token:
                return []
            resp = session.get(
                f"https://spclient.wg.spotify.com/user-profile-view/v3/profile/{user_id}/playlists",
                headers={"Authorization": f"Bearer {token}"},
                params={"limit": limit},
                timeout=15)
        if resp.status_code != 200:
            return []
        text = resp.content.decode("utf-8", errors="ignore")
        pids = re.findall(r"spotify:playlist:([a-zA-Z0-9]{22})", text)
        return list(dict.fromkeys(pids))
    except Exception:
        return []


def scrape_url(url, session):
    """Scrape a URL for emails and Spotify playlist/user links."""
    try:
        resp = session.get(url, timeout=20, headers={
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        if resp.status_code != 200:
            return [], [], []
        text = resp.text
        emails, igs = extract_contacts(text)
        pids = list(dict.fromkeys(re.findall(r"open\.spotify\.com/playlist/([a-zA-Z0-9]{22})", text)))
        user_ids = list(dict.fromkeys(re.findall(r"open\.spotify\.com/user/([a-zA-Z0-9_-]+)", text)))
        return emails, pids, user_ids
    except Exception:
        return [], [], []


# ── Known curator directory URLs ──
DIRECTORY_URLS = [
    "https://www.droptrack.com/spotify-playlist-curators/",
    "https://playlistsupply.com/",
    "https://www.whippedcreamsounds.com/find-spotify-playlist-curators/",
    "https://www.artist.tools/features/spotify-playlist-curators-contact-list",
    "https://recordlabel.ai/blog/spotify-playlist-curators-contact-list/",
    "https://play.soundplate.com/",
    "https://www.imusician.pro/en/resources/guides/find-playlist-curators",
    "https://www.musicpromotionusa.com/spotify-playlist-curators",
    "https://www.droptrack.com/spotify-playlist-curators/?genre=hip-hop",
    "https://www.droptrack.com/spotify-playlist-curators/?genre=r-b-soul",
    "https://www.droptrack.com/spotify-playlist-curators/?genre=pop",
    "https://www.droptrack.com/spotify-playlist-curators/?genre=lo-fi",
    "https://www.droptrack.com/spotify-playlist-curators/?genre=electronic",
    "https://www.droptrack.com/spotify-playlist-curators/?genre=indie",
    "https://www.droptrack.com/spotify-playlist-curators/?genre=jazz",
    "https://www.droptrack.com/spotify-playlist-curators/?genre=latin",
    "https://playlistsupply.com/browse/hip-hop",
    "https://playlistsupply.com/browse/r-and-b",
    "https://playlistsupply.com/browse/pop",
    "https://playlistsupply.com/browse/lo-fi",
    "https://playlistsupply.com/browse/electronic",
    "https://playlistsupply.com/browse/jazz",
    "https://playlistsupply.com/browse/indie",
    "https://play.soundplate.com/playlists?genre=hip-hop",
    "https://play.soundplate.com/playlists?genre=rnb",
    "https://play.soundplate.com/playlists?genre=pop",
    "https://play.soundplate.com/playlists?genre=lofi",
    "https://play.soundplate.com/playlists?genre=jazz",
    "https://play.soundplate.com/playlists?genre=electronic",
    "https://play.soundplate.com/playlists?genre=soul",
    "https://play.soundplate.com/playlists?genre=indie",
]


def load_existing(filename="output.csv"):
    rows = []
    seen_contacts = set()
    seen_ids = set()
    seen_users = set()
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
    return rows, seen_contacts, seen_ids, seen_users


def save_csv(rows, filename="output.csv"):
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main():
    target = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 1500

    existing_rows, seen_contacts, seen_ids, seen_users = load_existing()
    print(f"Loaded {len(existing_rows)} existing | {len(seen_ids)} playlist IDs | Need {max(0, target - len(existing_rows))} more\n")

    if len(existing_rows) >= target:
        print("Already at target!")
        return

    session = requests.Session()
    session.verify = False

    token_mgr = TokenManager()
    if not token_mgr.get_token():
        print("ERROR: No token")
        return
    print("Token ready.\n")

    all_rows = list(existing_rows)
    total_new = 0

    # ── Phase 1: Scrape directory websites ──
    print("=" * 60)
    print("PHASE 1: Scraping curator directory websites")
    print("=" * 60)

    all_dir_pids = []
    all_dir_emails = set()
    all_dir_users = set()

    for i, url in enumerate(DIRECTORY_URLS):
        if len(all_rows) >= target:
            break
        print(f"\n[{i+1}/{len(DIRECTORY_URLS)}] {url[:70]}...")
        emails, pids, user_ids = scrape_url(url, session)
        new_pids = [p for p in pids if p not in seen_ids]
        new_emails = [e for e in emails if e.lower() not in seen_contacts]
        print(f"  Found {len(pids)} playlists ({len(new_pids)} new), {len(emails)} emails ({len(new_emails)} new), {len(user_ids)} users")

        for e in new_emails:
            all_dir_emails.add(e)
        for p in new_pids:
            all_dir_pids.append(p)
        for u in user_ids:
            all_dir_users.add(u)

        # Scrape new playlists via wg endpoint
        hits = 0
        for pid in new_pids[:30]:
            seen_ids.add(pid)
            data = get_playlist_data(session, token_mgr, pid)
            if not data or data["editorial"]:
                continue

            # Merge directory emails with playlist emails
            merged_emails = list(set(data["emails"] + [e for e in new_emails if e.lower() not in seen_contacts]))
            instagrams = data["instagrams"]

            if not merged_emails and not instagrams:
                continue

            email_str = ", ".join(merged_emails[:3])
            ig_str = ", ".join(instagrams[:3])
            contact_key = (email_str or ig_str).lower()
            if contact_key in seen_contacts:
                continue
            seen_contacts.add(contact_key)

            # Track user for Phase 2
            if data.get("owner_uri") and data["owner_uri"].startswith("spotify:user:"):
                uid = data["owner_uri"].replace("spotify:user:", "")
                all_dir_users.add(uid)

            row = {
                "email": email_str,
                "instagram": ig_str,
                "playlist_name": data["name"],
                "playlist_url": f"https://open.spotify.com/playlist/{pid}",
                "keyword": "Directory",
                "description_snippet": data["description"][:100].replace("\n", " ") if data["description"] else "",
                "followers": "",
                "priority": "",
            }
            all_rows.append(row)
            total_new += 1
            hits += 1
            print(f"    HIT: {data['name'][:40]} | {email_str or ig_str}")
            time.sleep(random.uniform(0.2, 0.5))

        if hits > 0:
            save_csv(all_rows)
        time.sleep(random.uniform(2, 4))

    # Add standalone directory emails (not tied to a playlist)
    standalone_emails = [e for e in all_dir_emails if e.lower() not in seen_contacts]
    print(f"\n  Adding {len(standalone_emails)} standalone directory emails...")
    for email in standalone_emails:
        if len(all_rows) >= target:
            break
        seen_contacts.add(email.lower())
        row = {
            "email": email,
            "instagram": "",
            "playlist_name": "",
            "playlist_url": "",
            "keyword": "Directory Email",
            "description_snippet": "Curator email from directory site",
            "followers": "",
            "priority": "",
        }
        all_rows.append(row)
        total_new += 1
        print(f"    + {email}")

    save_csv(all_rows)
    print(f"\nPhase 1 done: +{total_new} | Total: {len(all_rows)}")

    # ── Phase 2: Discover more playlists from known curator user IDs ──
    if len(all_rows) < target:
        print(f"\n{'=' * 60}")
        print(f"PHASE 2: Mining curator user profiles ({len(all_dir_users)} users)")
        print(f"{'=' * 60}")

        # Also extract user IDs from existing playlist data
        for row in existing_rows:
            url = row.get("playlist_url", "")
            if "/playlist/" in url:
                pid = url.split("/playlist/")[-1].split("?")[0]
                # We'll get user IDs from the wg endpoint during scraping

        phase2_new = 0
        users_checked = 0

        for user_id in list(all_dir_users)[:100]:
            if len(all_rows) >= target:
                break
            if user_id in seen_users or user_id == "spotify":
                continue
            seen_users.add(user_id)
            users_checked += 1

            playlists = get_user_playlists_wg(session, token_mgr, user_id)
            new_pids = [p for p in playlists if p not in seen_ids]

            if not new_pids:
                continue

            print(f"\n  User {user_id}: {len(playlists)} playlists ({len(new_pids)} new)")

            for pid in new_pids[:20]:
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
                    "keyword": "User Profile",
                    "description_snippet": data["description"][:100].replace("\n", " ") if data["description"] else "",
                    "followers": "",
                    "priority": "",
                }
                all_rows.append(row)
                total_new += 1
                phase2_new += 1
                print(f"    HIT: {data['name'][:40]} | {email_str or ig_str}")
                time.sleep(random.uniform(0.2, 0.5))

            if phase2_new > 0 and users_checked % 5 == 0:
                save_csv(all_rows)

            if users_checked % 15 == 0:
                token_mgr.refresh()

            time.sleep(random.uniform(0.5, 1.5))

        save_csv(all_rows)
        print(f"\nPhase 2 done: +{phase2_new} | Total: {len(all_rows)}")

    # ── Phase 3: Mine existing playlist owners for more playlists ──
    if len(all_rows) < target:
        print(f"\n{'=' * 60}")
        print(f"PHASE 3: Mining owners of existing playlists for more contacts")
        print(f"{'=' * 60}")

        phase3_new = 0
        # Sample some existing playlist IDs to find their owners
        existing_pids = []
        for row in existing_rows:
            url = row.get("playlist_url", "")
            if "/playlist/" in url:
                existing_pids.append(url.split("/playlist/")[-1].split("?")[0])

        random.shuffle(existing_pids)

        for pid in existing_pids[:200]:
            if len(all_rows) >= target:
                break

            data = get_playlist_data(session, token_mgr, pid)
            if not data:
                continue

            owner_uri = data.get("owner_uri", "")
            if not owner_uri or not owner_uri.startswith("spotify:user:"):
                continue

            user_id = owner_uri.replace("spotify:user:", "")
            if user_id in seen_users or user_id == "spotify":
                continue
            seen_users.add(user_id)

            user_playlists = get_user_playlists_wg(session, token_mgr, user_id)
            new_pids = [p for p in user_playlists if p not in seen_ids]

            if not new_pids:
                continue

            for npid in new_pids[:10]:
                seen_ids.add(npid)
                ndata = get_playlist_data(session, token_mgr, npid)
                if not ndata or ndata["editorial"]:
                    continue
                if not ndata["emails"] and not ndata["instagrams"]:
                    continue

                email_str = ", ".join(ndata["emails"][:3])
                ig_str = ", ".join(ndata["instagrams"][:3])
                contact_key = (email_str or ig_str).lower()
                if contact_key in seen_contacts:
                    continue
                seen_contacts.add(contact_key)

                row = {
                    "email": email_str,
                    "instagram": ig_str,
                    "playlist_name": ndata["name"],
                    "playlist_url": f"https://open.spotify.com/playlist/{npid}",
                    "keyword": "Owner Mining",
                    "description_snippet": ndata["description"][:100].replace("\n", " ") if ndata["description"] else "",
                    "followers": "",
                    "priority": "",
                }
                all_rows.append(row)
                total_new += 1
                phase3_new += 1
                print(f"    HIT: {ndata['name'][:40]} | {email_str or ig_str}")

            time.sleep(random.uniform(0.3, 0.8))

            if phase3_new > 0 and phase3_new % 10 == 0:
                save_csv(all_rows)
                token_mgr.refresh()

        save_csv(all_rows)
        print(f"\nPhase 3 done: +{phase3_new} | Total: {len(all_rows)}")

    count = save_csv(all_rows)
    print(f"\n{'=' * 60}")
    print(f"FINAL: +{total_new} new contacts. {count} total in output.csv")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
