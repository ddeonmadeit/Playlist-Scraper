"""Wait for Spotify API rate limit to expire, then run the scraper.

Checks every 5 minutes if the API is accessible. Once it is, launches
the web_scraper with target 750 (to reach ~1500 total).
"""

import re
import time
import subprocess
import sys

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def get_token():
    s = requests.Session()
    s.verify = False
    s.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    resp = s.get("https://open.spotify.com/embed/playlist/37i9dQZF1DXcBWIGoYBM5M", timeout=15)
    tokens = re.findall(r'"accessToken":"([^"]+)"', resp.text)
    return tokens[0] if tokens else None


def check_api():
    token = get_token()
    if not token:
        return False, "No token"
    r = requests.get(
        "https://api.spotify.com/v1/search",
        headers={"Authorization": f"Bearer {token}"},
        params={"q": "test", "type": "playlist", "limit": 1},
        verify=False, timeout=15,
    )
    if r.status_code == 200:
        return True, "API is back!"
    elif r.status_code == 429:
        retry = r.headers.get("Retry-After", "?")
        return False, f"Still rate limited ({retry}s)"
    else:
        return False, f"Status {r.status_code}"


def main():
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 750
    check_interval = 300  # 5 minutes

    print("Waiting for Spotify API rate limit to expire...")
    print(f"Will run scraper with target={target} once API is available\n")

    while True:
        ok, msg = check_api()
        print(f"  [{time.strftime('%H:%M:%S')}] {msg}")

        if ok:
            print("\nAPI is accessible! Starting scraper...")
            subprocess.run([sys.executable, "src/web_scraper.py", str(target)])
            break

        time.sleep(check_interval)


if __name__ == "__main__":
    main()
