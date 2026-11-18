"""Collect public Coinbase Advanced BTC/ETH spot quotes; GET requests only."""
import argparse
import json
import os
from pathlib import Path
import tempfile
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from trading.regime import timestamp
from trading.runner import positive


def fetch_quote(asset, opener=None, clock=time.time):
    if asset not in ("BTC", "ETH"):
        raise ValueError("unsupported asset")
    product = f"{asset}-USD"
    url = "https://api.coinbase.com/api/v3/brokerage/market/product_book?" + urlencode({"product_id": product, "limit": 1})
    request = Request(url, headers={"User-Agent": "kronos-spot-paper", "Cache-Control": "no-cache"}, method="GET")
    started = clock()
    with (opener or urlopen)(request, timeout=5) as response:
        book = json.load(response)["pricebook"]
    received = clock()
    if received - started > 5 or received < started:
        raise ValueError("quote request was too slow or clock moved")
    if book["product_id"] != product:
        raise ValueError("book product mismatch")
    observed = timestamp(book["time"])
    if not observed <= received or received - observed > 10:
        raise ValueError("book timestamp is stale or future-dated")
    bid = positive(book["bids"][0]["price"], "bid")
    ask = positive(book["asks"][0]["price"], "ask")
    if bid > ask:
        raise ValueError("crossed book")
    return dict(venue="coinbase", asset=asset, product_id=product, quoted_at=observed,
                received_at=received, bid_usd=bid, ask_usd=ask,
                bid_size=positive(book["bids"][0]["size"], "bid size"),
                ask_size=positive(book["asks"][0]["size"], "ask size"),
                source="coinbase_advanced_public")


def collect():
    feed = {"quotes": [], "errors": []}
    for asset in ("BTC", "ETH"):
        try:
            feed["quotes"].append(fetch_quote(asset))
        except Exception as error:
            feed["errors"].append({"asset": asset, "error_type": type(error).__name__})
    return feed


def write_feed(path, feed):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".spot-quotes-")
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(feed, stream, allow_nan=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    try:
        while True:
            feed = collect()
            write_feed(args.output, feed)
            if args.once:
                print(json.dumps({"quotes": len(feed["quotes"]), "errors": feed["errors"], "orders_submitted": 0}))
                return 0 if len(feed["quotes"]) == 2 else 1
            time.sleep(2)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
