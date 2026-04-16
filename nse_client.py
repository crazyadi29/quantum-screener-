"""
NSE India API client — with auto cookie refresh and retry logic.
NSE cookies expire every few minutes; this client handles that transparently.
"""
import requests
import time
from urllib.parse import quote


class NSEClient:
    BASE = "https://www.nseindia.com"
    COOKIE_TTL = 240  # refresh cookies every 4 minutes

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nseindia.com/",
        })
        self._last_cookie_time = 0
        self._refresh_cookies()  # warm up on startup

    # ── Cookie Management ──────────────────────────────────────
    def _refresh_cookies(self):
        """Visit NSE homepage to get a valid session cookie."""
        try:
            self.session.get(f"{self.BASE}/", timeout=8)
            # Also hit the market-data page NSE uses as a session check
            self.session.get(
                f"{self.BASE}/market-data/live-equity-market", timeout=8
            )
            self._last_cookie_time = time.time()
            print("[nse] cookies refreshed")
        except Exception as e:
            print(f"[nse] cookie refresh failed: {e}")

    def _ensure_fresh_cookies(self):
        if time.time() - self._last_cookie_time > self.COOKIE_TTL:
            self._refresh_cookies()

    # ── Core GET ───────────────────────────────────────────────
    def _get(self, path):
        """GET request with auto cookie refresh on 401/403."""
        self._ensure_fresh_cookies()
        url = f"{self.BASE}{path}"
        try:
            r = self.session.get(url, timeout=8)

            # Cookie expired mid-session → refresh and retry once
            if r.status_code in (401, 403):
                print(f"[nse] {r.status_code} on {path} — refreshing cookies")
                self._refresh_cookies()
                r = self.session.get(url, timeout=8)

            if r.status_code == 200:
                ct = r.headers.get("content-type", "")
                if "json" in ct:
                    return r.json()
            print(f"[nse] {path} status={r.status_code}")
            return None
        except Exception as e:
            print(f"[nse] error {path}: {e}")
            return None

    # ── Index data ─────────────────────────────────────────────
    def get_index_quote(self, index_name="NIFTY 50"):
        data = self._get("/api/allIndices")
        if not data:
            return None
        for idx in data.get("data", []):
            if idx.get("index", "").upper() == index_name.upper():
                return {
                    "price": idx.get("last", 0),
                    "change": round(idx.get("change", 0), 2),
                    "changePct": round(idx.get("percentChange", 0), 2),
                    "open": idx.get("open", 0),
                    "high": idx.get("high", 0),
                    "low": idx.get("low", 0),
                    "prevClose": idx.get("previousClose", 0),
                }
        return None

    def get_all_indices(self):
        data = self._get("/api/allIndices")
        if not data:
            return {}
        result = {}
        for idx in data.get("data", []):
            name = idx.get("index", "")
            result[name] = {
                "price": idx.get("last", 0),
                "change": round(idx.get("change", 0), 2),
                "changePct": round(idx.get("percentChange", 0), 2),
                "prevClose": idx.get("previousClose", 0),
            }
        return result

    # ── Stock quote ────────────────────────────────────────────
    def get_stock_quote(self, symbol):
        encoded = quote(symbol)
        data = self._get(f"/api/quote-equity?symbol={encoded}")
        if not data:
            return None
        info = data.get("priceInfo", {})
        return {
            "price": info.get("lastPrice", 0),
            "change": round(info.get("change", 0), 2),
            "changePct": round(info.get("pChange", 0), 2),
            "open": info.get("open", 0),
            "high": info.get("intraDayHighLow", {}).get("max", 0),
            "low": info.get("intraDayHighLow", {}).get("min", 0),
            "prevClose": info.get("previousClose", 0),
        }

    # ── Option Chain ───────────────────────────────────────────
    def get_option_chain(self, symbol):
        nse_sym = symbol.replace(".NS", "")
        if nse_sym == "^NSEI":
            nse_sym = "NIFTY"

        if nse_sym in ("NIFTY", "BANKNIFTY", "FINNIFTY"):
            path = f"/api/option-chain-indices?symbol={nse_sym}"
        else:
            path = f"/api/option-chain-equities?symbol={quote(nse_sym)}"

        data = self._get(path)
        if not data:
            return {
                "error": "NSE unavailable",
                "mock": True,
                "call_oi": 450000,
                "put_oi": 380000,
            }

        records = data.get("records", {}).get("data", [])
        max_call_oi, max_put_oi = 0, 0
        for item in records:
            max_call_oi = max(max_call_oi, item.get("CE", {}).get("openInterest", 0))
            max_put_oi  = max(max_put_oi,  item.get("PE", {}).get("openInterest", 0))

        if max_call_oi == 0 and max_put_oi == 0:
            return {
                "error": "Market closed / empty OI",
                "mock": True,
                "call_oi": 450000,
                "put_oi": 380000,
            }

        return {
            "mock": False,
            "call_oi": max_call_oi,
            "put_oi": max_put_oi,
            "error": None,
        }


nse_client = NSEClient()
