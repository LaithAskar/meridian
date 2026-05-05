"""One-off: pull RH order history for 2026-05-04, focus on AMD and PLTR ghost orders.
Run from project root with: .venv/Scripts/python.exe investigate_orders.py"""
from dotenv import load_dotenv
load_dotenv()
import os
import json
import robin_stocks.robinhood as rh

rh.login(
    os.getenv("ROBINHOOD_USERNAME"),
    os.getenv("ROBINHOOD_PASSWORD"),
    store_session=True,
)

orders = rh.orders.get_all_stock_orders() or []
print(f"Total orders fetched: {len(orders)}")

# Cache instrument-url -> symbol lookups
symbol_cache: dict[str, str] = {}
def sym(url: str) -> str:
    if url in symbol_cache:
        return symbol_cache[url]
    try:
        inst = rh.stocks.get_instrument_by_url(url) or {}
        s = inst.get("symbol", "?")
    except Exception:
        s = "?"
    symbol_cache[url] = s
    return s

target_date = "2026-05-04"
target_symbols = {"AMD", "PLTR", "MSFT", "META", "TSLA", "RIVN", "AAPL", "NVDA"}

print(f"\n=== Orders from {target_date} ===")
for o in orders:
    created = o.get("created_at", "")
    if not created.startswith(target_date):
        continue
    s = sym(o.get("instrument", ""))
    state = o.get("state")
    cancel = o.get("cancel")
    qty = o.get("quantity")
    price = o.get("price") or o.get("average_price")
    side = o.get("side")
    reject = o.get("reject_reason")
    msg = f"  {s:6s} {side:4s} qty={qty} price={price} state={state}"
    if reject:
        msg += f" reject={reject}"
    if cancel:
        msg += f" cancel_url=present"
    print(msg)
    if s in ("AMD", "PLTR"):
        print(f"    FULL: {json.dumps({k: v for k, v in o.items() if k not in ('url', 'instrument', 'account', 'cancel')}, indent=6)}")
