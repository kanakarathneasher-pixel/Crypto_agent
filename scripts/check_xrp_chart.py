"""Read-only live chart connectivity check; no strategy or order endpoints."""
import json
import time
from backend.xrp_chart import PublicTicker, history


def check():
    seed = history('1D')
    print(f"History: {seed['product']}, {len(seed['points'])} actual completed prices", flush=True)
    feed = PublicTicker()
    feed.start()
    try:
        deadline = time.monotonic()+20
        while time.monotonic()<deadline:
            snapshot = feed.snapshot()
            if snapshot['fresh']:
                print(json.dumps(snapshot), flush=True)
                return
            time.sleep(.5)
        raise RuntimeError('No fresh Coinbase XRP-USD ticker received within 20 seconds.')
    finally:
        feed.stop()


if __name__ == '__main__':
    check()
