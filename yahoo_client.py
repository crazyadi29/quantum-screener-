"""
Yahoo Finance v8 Chart API client — market-hours-aware live pricing.

- Market OPEN  (9:15–15:30 IST, Mon–Fri): uses 1-minute interval → near-live price
- Market CLOSED: uses daily interval → last session's closing price
"""
import requests
import time
import pytz
from datetime import datetime, time as dtime
from urllib.parse import quote

IST = pytz.timezone("Asia/Kolkata")


def _is_market_open() -> bool:
    now = datetime.now(IST)
    if now.weekday() >= 5:  # Saturday / Sunday
        return False
    t = now.time()
    return dtime(9, 15) <= t <= dtime(15, 30)


class YahooClient:
    """Lightweight Yahoo Finance client using the v8 chart endpoint."""

    BASE = "https://query1.finance.yahoo.com/v8/finance/chart"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://finance.yahoo.com/",
            "Origin": "https://finance.yahoo.com",
        })
        self.crumb = None

    # ── chart data ──────────────────────────────────────────────
    def get_chart(self, symbol, range_val="90d", interval="1d"):
        """Fetch OHLCV chart data.

        Returns list of dicts:  timestamp, open, high, low, close, volume
        """
        encoded = quote(symbol, safe="^.")
        url = (
            f"{self.BASE}/{encoded}"
            f"?range={range_val}&interval={interval}&includePrePost=false"
        )

        for attempt in range(2):
            try:
                res = self.session.get(url, timeout=6)
                if res.status_code == 404:
                    return None
                if res.status_code != 200:
                    if attempt == 0:
                        time.sleep(0.3)
                        continue
                    return None

                data = res.json()
                result = data.get("chart", {}).get("result")
                if not result:
                    return None

                r = result[0]
                timestamps = r.get("timestamp") or []
                q = (r.get("indicators", {}).get("quote") or [{}])[0]

                opens   = q.get("open",   [])
                highs   = q.get("high",   [])
                lows    = q.get("low",    [])
                closes  = q.get("close",  [])
                volumes = q.get("volume", [])

                out = []
                for i in range(len(timestamps)):
                    if i >= len(closes) or closes[i] is None:
                        continue
                    out.append({
                        "timestamp": timestamps[i],
                        "open":   opens[i]   if i < len(opens)   and opens[i]   is not None else closes[i],
                        "high":   highs[i]   if i < len(highs)   and highs[i]   is not None else closes[i],
                        "low":    lows[i]    if i < len(lows)    and lows[i]    is not None else closes[i],
                        "close":  closes[i],
                        "volume": volumes[i] if i < len(volumes) and volumes[i] is not None else 0,
                    })
                return out if out else None

            except Exception as e:
                print(f"[yahoo] chart error {symbol} attempt={attempt}: {e}")
                if attempt == 0:
                    time.sleep(0.3)
        return None

    # ── live quote ──────────────────────────────────────────────
    def get_live_quote(self, symbol):
        """Return current price data, aware of market hours.

        - Market OPEN:   fetches 1-min candles → latest price with minimal latency
        - Market CLOSED: fetches last 5 daily candles → last session close price
        """
        if _is_market_open():
            return self._live_intraday_quote(symbol)
        else:
            return self._last_session_quote(symbol)

    def _live_intraday_quote(self, symbol):
        """Use 1-minute bars for near-realtime price during market hours."""
        # Get today's 1-min candles
        intraday = self.get_chart(symbol, range_val="1d", interval="1m")

        # Get previous close from recent daily data
        daily = self.get_chart(symbol, range_val="5d", interval="1d")
        if daily and len(daily) >= 2:
            prev_close = daily[-2]["close"]
        elif daily:
            prev_close = daily[-1]["open"]
        else:
            prev_close = None

        if not intraday:
            # Intraday unavailable → fall back to last session
            print(f"[yahoo] intraday unavailable for {symbol}, using daily fallback")
            return self._last_session_quote(symbol)

        curr = intraday[-1]  # most recent 1-min candle

        # If prev_close still missing, derive from today's open
        if prev_close is None:
            prev_close = intraday[0]["open"]

        change = curr["close"] - prev_close
        change_pct = (change / prev_close * 100) if prev_close else 0.0

        # Aggregate today's high / low / volume from all intraday candles
        day_high   = max(c["high"]   for c in intraday)
        day_low    = min(c["low"]    for c in intraday)
        day_volume = sum(c["volume"] for c in intraday)

        return {
            "price":     round(curr["close"], 2),
            "open":      round(intraday[0]["open"], 2),
            "high":      round(day_high, 2),
            "low":       round(day_low, 2),
            "prevClose": round(prev_close, 2),
            "change":    round(change, 2),
            "changePct": round(change_pct, 2),
            "volume":    day_volume,
            "live":      True,
        }

    def _last_session_quote(self, symbol):
        """Return last session's closing data when market is closed."""
        chart = self.get_chart(symbol, range_val="5d", interval="1d")
        if not chart:
            return None

        if len(chart) >= 2:
            prev_close = chart[-2]["close"]
            curr = chart[-1]
        else:
            prev_close = chart[0]["open"]
            curr = chart[0]

        change = curr["close"] - prev_close
        change_pct = (change / prev_close * 100) if prev_close else 0.0

        return {
            "price":     round(curr["close"], 2),
            "open":      round(curr["open"], 2),
            "high":      round(curr["high"], 2),
            "low":       round(curr["low"], 2),
            "prevClose": round(prev_close, 2),
            "change":    round(change, 2),
            "changePct": round(change_pct, 2),
            "volume":    curr["volume"],
            "live":      False,
        }

    # ── analyst recommendations ─────────────────────────────────
    def _init_crumb(self):
        try:
            self.session.get("https://fc.yahoo.com", timeout=4)
            r = self.session.get(
                "https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=4
            )
            if r.status_code == 200:
                self.crumb = r.text.strip()
        except Exception as e:
            print(f"[yahoo] crumb init failed: {e}")

    def get_recommendations(self, symbol):
        if not self.crumb:
            self._init_crumb()
        encoded = quote(symbol, safe="^.")
        url = (
            f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/"
            f"{encoded}?modules=recommendationTrend&crumb={self.crumb}"
        )
        try:
            r = self.session.get(url, timeout=4)
            if r.status_code == 401:
                self._init_crumb()
                r = self.session.get(url, timeout=4)
            if r.status_code != 200:
                return None
            result = r.json().get("quoteSummary", {}).get("result", [])
            if not result:
                return None
            trends = result[0].get("recommendationTrend", {}).get("trend", [])
            return trends[0] if trends else None
        except Exception as e:
            print(f"[yahoo] reco error {symbol}: {e}")
            return None


yahoo_client = YahooClient()
