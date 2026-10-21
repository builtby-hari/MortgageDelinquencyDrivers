"""Download FRED series into data/ as CSV. No API key needed.

Series: DRSFRMACBS (delinquency, quarterly), UNRATE (unemployment, monthly),
MORTGAGE30US (30-year rate, weekly).
Usage: python3 fetch_fred.py
"""

import os
import time
import urllib.error
import urllib.request

SERIES = ["DRSFRMACBS", "UNRATE", "MORTGAGE30US"]
URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
RETRY_DELAYS = (2, 4, 4)  # seconds before each of the 3 retries


def fetch(series_id: str) -> str:
    url = URL.format(series_id)
    # Default urllib User-Agent on purpose: FRED stalls requests with custom User-Agents.
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                return resp.read().decode("utf-8")
        except (urllib.error.URLError, OSError):
            if attempt == len(RETRY_DELAYS):
                raise
            time.sleep(RETRY_DELAYS[attempt])


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    for sid in SERIES:
        text = fetch(sid)
        with open(os.path.join(DATA_DIR, f"{sid}.csv"), "w") as f:
            f.write(text)
        print(f"{sid:<13} {text.count(chr(10)) - 1:>6} rows")


if __name__ == "__main__":
    main()
