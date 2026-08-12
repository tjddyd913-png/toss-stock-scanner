from flask import Flask, render_template, request, jsonify
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

app = Flask(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0"}

def chart(symbol, interval="1m", range_="5d"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"interval": interval, "range": range_, "includePrePost": "true"}
    r = requests.get(url, params=params, headers=HEADERS, timeout=12)
    r.raise_for_status()
    result = r.json()["chart"]["result"]
    if not result:
        raise ValueError("시세 데이터 없음")
    return result[0]

def intraday_rows(result):
    ts = result.get("timestamp") or []
    q = result["indicators"]["quote"][0]
    closes = q.get("close") or []
    highs = q.get("high") or []
    lows = q.get("low") or []
    vols = q.get("volume") or []
    rows = []
    for i, t in enumerate(ts):
        if i >= len(closes) or closes[i] is None:
            continue
        dt = datetime.fromtimestamp(t, ZoneInfo("America/New_York"))
        rows.append({
            "dt": dt,
            "close": closes[i],
            "high": highs[i] if i < len(highs) else None,
            "low": lows[i] if i < len(lows) else None,
            "volume": vols[i] if i < len(vols) and vols[i] is not None else 0
        })
    if not rows:
        return []
    d = rows[-1]["dt"].date()
    return [x for x in rows if x["dt"].date() == d]

def scan_one(symbol):
    symbol = symbol.strip().upper()
    result = chart(symbol, "1m", "5d")
    meta = result.get("meta", {})
    rows = intraday_rows(result)
    if not rows:
        raise ValueError("오늘 분봉 데이터 없음")

    price = float(meta.get("regularMarketPrice") or rows[-1]["close"])
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    prev = float(prev) if prev else None
    change = ((price / prev) - 1) * 100 if prev else None

    day_volume = int(sum(x["volume"] for x in rows))

    pv = 0.0
    vv = 0
    for x in rows:
        typical = x["close"] if x["high"] is None or x["low"] is None else (x["high"] + x["low"] + x["close"]) / 3
        pv += typical * x["volume"]
        vv += x["volume"]
    vwap = pv / vv if vv else None

    daily = chart(symbol, "1d", "1mo")
    vols = daily["indicators"]["quote"][0].get("volume") or []
    clean = [float(v) for v in vols if v]
    hist = clean[-21:-1] if len(clean) > 1 else []
    avg20 = sum(hist) / len(hist) if hist else None
    rvol = day_volume / avg20 if avg20 else None

    return {
        "symbol": symbol,
        "price": price,
        "change": change,
        "volume": day_volume,
        "rvol": rvol,
        "vwap": vwap,
        "above_vwap": (price >= vwap) if vwap else None,
        "updated": datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S KST")
    }

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/api/scan", methods=["POST"])
def scan():
    body = request.get_json(force=True)
    symbols = body.get("symbols", [])
    s = body.get("settings", {})
    out = []
    for sym in symbols[:30]:
        try:
            x = scan_one(sym)
            checks = {
                "상승률": x["change"] is not None and x["change"] >= float(s.get("minChange", 0)),
                "RVOL": x["rvol"] is not None and x["rvol"] >= float(s.get("minRvol", 0)),
                "거래량": x["volume"] >= int(s.get("minVolume", 0)),
                "VWAP": (not bool(s.get("aboveVwap", False))) or bool(x["above_vwap"])
            }
            x["checks"] = checks
            x["passed"] = all(checks.values())
            out.append(x)
        except Exception as e:
            out.append({"symbol": sym.upper(), "error": str(e), "passed": False})
    return jsonify({"results": out})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
