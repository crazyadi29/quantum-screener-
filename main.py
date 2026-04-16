import sys
import os
import asyncio
import json
from datetime import datetime, time as dtime
import pytz

sys.path.append(os.path.dirname(__file__))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

IST = pytz.timezone("Asia/Kolkata")

# ─── Market Hours ──────────────────────────────────────────────────────────────

def is_market_open() -> bool:
    now = datetime.now(IST)
    if now.weekday() >= 5:          # Saturday / Sunday
        return False
    t = now.time()
    return dtime(9, 15) <= t <= dtime(15, 30)

def market_status_label() -> str:
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return "WEEKEND"
    t = now.time()
    if t < dtime(9, 15):
        return "PRE-MARKET"
    if t <= dtime(15, 30):
        return "MARKET OPEN"
    return "MARKET CLOSED"

# ─── WebSocket Manager ─────────────────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, data: dict):
        dead = []
        for ws in self.active_connections:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

manager = ConnectionManager()

# ─── Live Tick Broadcaster ─────────────────────────────────────────────────────

async def live_tick_broadcaster():
    """
    Broadcasts market data to all WebSocket clients every 5 seconds.
    - Market OPEN:   live prices from NSE / Yahoo intraday
    - Market CLOSED: last session prices from Yahoo daily
    """
    while True:
        try:
            if manager.active_connections:
                from logic.market_logic import get_market_trend, get_sector_performances
                loop = asyncio.get_event_loop()

                trend   = await loop.run_in_executor(None, get_market_trend)
                sectors = await loop.run_in_executor(None, get_sector_performances)

                now_ist    = datetime.now(IST)
                open_flag  = is_market_open()
                status_lbl = market_status_label()

                payload = {
                    "type":          "tick",
                    "market_open":   open_flag,
                    "market_status": status_lbl,
                    "timestamp":     now_ist.strftime("%H:%M:%S IST"),
                    "trend":         trend,
                    "sectors":       sectors,
                }
                await manager.broadcast(payload)

        except Exception as e:
            print(f"[LiveTick] Error: {e}")

        # Poll every 5 s while open, every 60 s while closed (save API quota)
        await asyncio.sleep(5 if is_market_open() else 60)


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(live_tick_broadcaster())

# ─── REST Endpoints ────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    now = datetime.now(IST)
    return {
        "status":        "ok",
        "time_ist":      now.strftime("%d %b %Y %H:%M:%S IST"),
        "market_open":   is_market_open(),
        "market_status": market_status_label(),
    }

@app.get("/api/market-trend")
def market_trend():
    from logic.market_logic import get_market_trend
    data            = get_market_trend()
    data["market_open"]   = is_market_open()
    data["market_status"] = market_status_label()
    data["timestamp"]     = datetime.now(IST).strftime("%H:%M:%S IST")
    return JSONResponse(content=data)

@app.get("/api/sectors")
def sectors():
    from logic.market_logic import get_sector_performances
    return JSONResponse(content=get_sector_performances())

@app.get("/api/stock-analysis")
def stock_analysis(sector: str, trend: str = "positive"):
    from logic.market_logic import analyze_sector_stocks
    from logic.fo_stocks import FO_SECTORS
    if sector not in FO_SECTORS:
        return JSONResponse(content={"error": "Invalid sector"}, status_code=400)
    return JSONResponse(content=analyze_sector_stocks(sector, trend))

@app.get("/api/option-chain/{symbol}")
def option_chain(symbol: str):
    from logic.nse_client import nse_client
    data = nse_client.get_option_chain(symbol)
    return JSONResponse(content=data)

@app.get("/api/chart-data/{symbol}")
def api_chart_data(symbol: str):
    from logic.market_logic import get_chart_data
    data = get_chart_data(symbol)
    if not data or "error" in data:
        return JSONResponse(content={"error": "No data"}, status_code=404)
    return JSONResponse(content=data)

@app.get("/api/search")
def search(q: str = ""):
    from logic.market_logic import search_fo_stocks
    return JSONResponse(content=search_fo_stocks(q))

# ─── WebSocket Endpoint ────────────────────────────────────────────────────────

@app.websocket("/ws/live")
async def websocket_live(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # Fire an immediate tick on connect so UI doesn't wait 5 s
        from logic.market_logic import get_market_trend, get_sector_performances
        loop = asyncio.get_event_loop()
        trend   = await loop.run_in_executor(None, get_market_trend)
        sectors = await loop.run_in_executor(None, get_sector_performances)
        now_ist = datetime.now(IST)
        await websocket.send_json({
            "type":          "tick",
            "market_open":   is_market_open(),
            "market_status": market_status_label(),
            "timestamp":     now_ist.strftime("%H:%M:%S IST"),
            "trend":         trend,
            "sectors":       sectors,
        })
        # Keep alive — broadcaster handles subsequent ticks
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"[WS] Error: {e}")
        manager.disconnect(websocket)
