"""Batch scrape playlist IDs via wg endpoint + add directory-sourced emails."""

import csv
import re
import time
import random
import os
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

# Playlist IDs from directory pages
DIRECTORY_PIDS = [
    # iMusician page
    "37i9dQZF1DX0XUsuxWHRQd", "37i9dQZF1DWTggY0yqBxES", "37i9dQZF1DWY6tYEFs22tT",
    "38rSkTivyQzJ6C2SMz4YzO", "49zsXPRUYaczLjv1KQqdyq", "1xtRE3jcX4IuU3nfZfEEc6",
    "3MhvetepLZDSmayigRpTAL", "2O1NjpfM3A4tj9QyfnUF95", "2rwIoo35NITJ4VeWkdtwBU",
    "4hfPP7BZZHffHvk2ej4SET", "3BinEmzsOm7tiIJjjYDPwI", "4XOIhDN3APW4EJuU32uFYW",
    # MusicPromotionUSA page
    "119lZx2EHKZur335RveqMc", "551T9pXxgeqs36NMBSy0eb", "0oWZjR0F6qhPSryDRQcbKn",
    "6K6R2y9QFr9yrUoHNkBSH5", "1eCwLTSfr6HGd7URHd4cpZ", "2jHbztkuPjoBO6FN3dtoL1",
    "64OX1gQhI2NZxjPb4z3erl", "3dd65gH0SbHJrNBLbAKlmN", "6NyANZ6bIdvrrEtNFeA3SD",
    "59y1SSfAYf2DE4PmHhwNh1", "1E3z5TOh1SVfMF134q8PtJ", "2YBRZBWjiVy2KFdu4kNZcz",
    "38KngtbWE1PROJhtUFKBgi", "1OyXhXTwcluDbpCjWQICn7", "54iTPgN7HTsc8BkJoowNXK",
    "1ZfkYSu3HHMa9jcRU4DnIw", "73BborrYiSSSnMKflh8g80", "5LZxGygDEVzxglj9iCsxbB",
    "7xBH6HAUcaxLpAK5xv0Gso", "2nDzT3zrSy1I1Upw3k73YP", "0XrGyL1BNgwhBtmWrk1i1d",
    "4bHIl5A3vizYVGsFJMkq5k", "0B5izZIqDGbWbiV5GfPlU2", "7DyhMKOrMtaA1aGpcF9KuU",
    "4m8KUR2Js0gLXUrYpWgKFC", "5IgTRRVwq2UEN5T1iCBJNN", "4slmOJp5zJRjT03bXG4VRV",
    # Stereofox
    "2qbX2bg93iLsSBmf1OG6Zw", "2pIiS1gGHjq8RiC4PB1iUP",
    # Search results
    "3frGDueBhkbzXv6wgEWCN6", "4pDruJuXgUN7ZAZI6GyOiG",
    "05OkqemhVmD27zXfdnyNsy", "3BOxfexQyBa1tsEZ1tJFVQ",
]

# Emails found directly from directory pages (with playlist context)
DIRECTORY_EMAILS = [
    # iMusician
    {"email": "dailyrapfacts@gmail.com", "playlist_name": "Daily Rap Facts", "keyword": "iMusician directory"},
    {"email": "submit.playlisternetwork@gmail.com", "playlist_name": "Playlister Network", "keyword": "iMusician directory"},
    {"email": "SubmitYourMusic@protonmail.com", "playlist_name": "Submit Your Music", "keyword": "iMusician directory"},
    {"email": "slappersplaylists@gmail.com", "playlist_name": "Slappers Playlists", "keyword": "iMusician directory"},
    # MusicPromotionUSA
    {"email": "coltonvennermusic@gmail.com", "playlist_name": "Colton Venner Music", "keyword": "MusicPromotionUSA directory"},
    {"email": "dyc@lightsandmusic.com", "playlist_name": "Lights and Music", "keyword": "MusicPromotionUSA directory"},
    {"email": "dyctonight@gmail.com", "playlist_name": "DYC Tonight", "keyword": "MusicPromotionUSA directory"},
    {"email": "spotify@florian.jensen", "playlist_name": "Florian Jensen", "keyword": "MusicPromotionUSA directory"},
    {"email": "Sam@indiemono.com", "playlist_name": "Indiemono", "keyword": "MusicPromotionUSA directory"},
    {"email": "IMMplaylist@gmail.com", "playlist_name": "IMM Playlist", "keyword": "MusicPromotionUSA directory"},
    {"email": "info@experiencemusicgroup.com", "playlist_name": "Experience Music Group", "keyword": "MusicPromotionUSA directory"},
    {"email": "info@streamthatmusic.com", "playlist_name": "Stream That Music", "keyword": "MusicPromotionUSA directory"},
    {"email": "demos@islandbeatsmusic.com", "playlist_name": "Island Beats Music", "keyword": "MusicPromotionUSA directory"},
    {"email": "info@neelsvisser.com", "playlist_name": "Neels Visser", "keyword": "MusicPromotionUSA directory"},
    {"email": "wooko@bassboostofficial.com", "playlist_name": "Bass Boost Official", "keyword": "MusicPromotionUSA directory"},
    {"email": "digital@timerec.it", "playlist_name": "Time Records", "keyword": "MusicPromotionUSA directory"},
    {"email": "cabin@northernstreams.us", "playlist_name": "Northern Streams", "keyword": "MusicPromotionUSA directory"},
    {"email": "kontakt@marcinmrotek.pl", "playlist_name": "Marcin Mrotek", "keyword": "MusicPromotionUSA directory"},
    {"email": "gnashmgmt@gmail.com", "playlist_name": "GNASH MGMT", "keyword": "MusicPromotionUSA directory"},
    {"email": "contact@prettylightsmusic.com", "playlist_name": "Pretty Lights Music", "keyword": "MusicPromotionUSA directory"},
    {"email": "cleanpopplaylist@gmail.com", "playlist_name": "Clean Pop Playlist", "keyword": "MusicPromotionUSA directory"},
    {"email": "nbillie1229@gmail.com", "playlist_name": "NBillie", "keyword": "MusicPromotionUSA directory"},
    {"email": "info@thisisangelique.com", "playlist_name": "Angelique", "keyword": "MusicPromotionUSA directory"},
    {"email": "Todaysraphits@gmail.com", "playlist_name": "Today's Rap Hits", "keyword": "MusicPromotionUSA directory"},
    {"email": "promotingsoundsspotify@gmail.com", "playlist_name": "Promoting Sounds", "keyword": "MusicPromotionUSA directory"},
]


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


def get_token():
    s = requests.Session()
    s.verify = False
    s.headers["User-Agent"] = random.choice(USER_AGENTS)
    pid = random.choice(TOKEN_PLAYLISTS)
    resp = s.get(f"https://open.spotify.com/embed/playlist/{pid}", timeout=15)
    tokens = re.findall(r'"accessToken":"([^"]+)"', resp.text)
    return tokens[0] if tokens else None


def extract_contacts(text):
    if not text:
        return [], []
    emails = EMAIL_REGEX.findall(text)
    emails = [e for e in emails if e.lower() not in EMAIL_BLACKLIST
              and not e.endswith((".png", ".jpg", ".svg", ".gif", ".css", ".js"))]
    raw_ig = INSTAGRAM_REGEX.findall(text)
    instagrams = [h for h in raw_ig if h.lower() not in IG_STOPWORDS and len(h) > 2]
    return list(set(emails)), list(set(instagrams))


def get_playlist_name(session, pid):
    try:
        resp = session.get(
            f"https://open.spotify.com/oembed?url=https://open.spotify.com/playlist/{pid}",
            timeout=10)
        if resp.status_code == 200:
            return resp.json().get("title", "")
    except Exception:
        pass
    return ""


def main():
    existing_rows, seen_contacts, seen_ids = load_existing()
    print(f"Loaded {len(existing_rows)} existing, {len(seen_contacts)} contacts, {len(seen_ids)} IDs")

    session = requests.Session()
    session.verify = False
    session.headers["User-Agent"] = random.choice(USER_AGENTS)

    token = get_token()
    if not token:
        print("ERROR: no token")
        return
    print(f"Token acquired")

    all_rows = list(existing_rows)
    total_new = 0

    # Phase 1: Add directory emails directly
    print(f"\n=== Phase 1: Adding {len(DIRECTORY_EMAILS)} directory emails ===")
    for entry in DIRECTORY_EMAILS:
        email = entry["email"]
        if email.lower() in seen_contacts:
            continue
        seen_contacts.add(email.lower())

        row = {
            "email": email,
            "instagram": "",
            "playlist_name": entry["playlist_name"],
            "playlist_url": "",
            "keyword": entry["keyword"],
            "description_snippet": "",
            "followers": "",
            "priority": "",
        }
        all_rows.append(row)
        total_new += 1
        print(f"  + {entry['playlist_name']} | {email}")

    count = save_csv(all_rows)
    print(f"  Added {total_new} directory emails. Total: {count}")

    # Phase 2: Scrape directory playlist IDs via wg endpoint
    print(f"\n=== Phase 2: Scraping {len(DIRECTORY_PIDS)} directory playlist IDs ===")
    for pid in DIRECTORY_PIDS:
        if pid in seen_ids:
            continue
        seen_ids.add(pid)

        try:
            resp = session.get(
                f"https://spclient.wg.spotify.com/playlist/v2/playlist/{pid}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )
            if resp.status_code == 401:
                token = get_token()
                if not token:
                    break
                resp = session.get(
                    f"https://spclient.wg.spotify.com/playlist/v2/playlist/{pid}",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=15,
                )
            if resp.status_code != 200:
                continue

            text = resp.content.decode("utf-8", errors="ignore")
            emails, instagrams = extract_contacts(text)

            if not emails and not instagrams:
                continue

            email_str = ", ".join(emails)
            ig_str = ", ".join(instagrams)
            contact_key = (email_str or ig_str).lower()
            if contact_key in seen_contacts:
                continue
            seen_contacts.add(contact_key)

            name = get_playlist_name(session, pid)

            row = {
                "email": email_str,
                "instagram": ig_str,
                "playlist_name": name,
                "playlist_url": f"https://open.spotify.com/playlist/{pid}",
                "keyword": "directory_scrape",
                "description_snippet": "",
                "followers": "",
                "priority": "",
            }
            all_rows.append(row)
            total_new += 1
            print(f"  + {name} | {email_str or ig_str}")

        except Exception as e:
            continue

        time.sleep(random.uniform(0.3, 0.8))

    count = save_csv(all_rows)
    print(f"\n=== DONE! +{total_new} new contacts. {count} total ===")


if __name__ == "__main__":
    main()
