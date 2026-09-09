"""Read-only runtime smoke check for the built frontend and private API session.

Run: python -m scripts.http_smoke --url http://127.0.0.1:8000
Does not submit research or make model/search requests.
"""

import argparse
import re
from urllib.parse import urljoin, urlsplit

import httpx


def main(base):
    with httpx.Client(base_url=base, timeout=10, trust_env=False) as client:
        root = client.get("/")
        root.raise_for_status()
        assert "Fieldwork" in root.text, "Frontend title missing"
        assets = set(re.findall(r'(?:src|href)="([^\"]+\.(?:js|css))"', root.text))
        assert assets, "No compiled assets referenced by the frontend"
        for asset in assets:
            url = urljoin(base, asset)
            assert urlsplit(url).netloc == urlsplit(base).netloc, "Unexpected external asset"
            client.get(url).raise_for_status()
        client.get("/api/health").raise_for_status()
        session = client.get("/api/session")
        session.raise_for_status()
        assert "fieldwork_session" in client.cookies, "Session cookie missing"
        history = client.get("/api/research")
        history.raise_for_status()
        assert isinstance(history.json(), list)
        assert history.headers["cache-control"] == "no-store"
        print(
            f"PASS: frontend, {len(assets)} compiled assets, health, session, and private history."
        )
        print(f"Research configured: {session.json()['configured']}. No research was submitted.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    main(parser.parse_args().url)
