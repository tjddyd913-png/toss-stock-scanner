from flask import Flask, render_template, request, jsonify
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

app = Flask(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

NY = ZoneInfo("America/New_York")
KST = ZoneInfo("Asia/Seoul")


def chart(symbol, interval="1m", range_="5d"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

    params = {
        "interval": interval,
        "range": range_,
        "includePrePost": "true",
        "events": "div,splits"
    }

    r = requests.get(
        url,
        params=params,
        headers=HEADERS,
        timeout=12
    )

    r.raise_for_status()

    data = r.json()

    result = data.get("chart", {}).get("result")

    if not result:
        raise ValueError("시세 데이터 없음")

    return result[0]


def make_rows(result):

    ts = result.get("timestamp") or []

    indicators = result.get("indicators", {})
    quotes = indicators.get("quote") or []

    if not quotes:
        return []

    q = quotes[0]

    closes = q.get("close") or []
    highs = q.get("high") or []
    lows = q.get("low") or []
    vols = q.get("volume") or []

    rows = []

    for i, t in enumerate(ts):

        if i >= len(closes):
            continue

        close = closes[i]

        if close is None:
            continue

        dt = datetime.fromtimestamp(t, NY)

        high = highs[i] if i < len(highs) else None
        low = lows[i] if i < len(lows) else None
        volume = vols[i] if i < len(vols) else 0

        rows.append({
            "dt": dt,
            "close": float(close),
            "high": float(high) if high is not None else None,
            "low": float(low) if low is not None else None,
            "volume": int(volume or 0)
        })

    return rows


def current_trading_day(rows):

    if not rows:
        return []

    latest_date = rows[-1]["dt"].date()

    return [
        x for x in rows
        if x["dt"].date() == latest_date
    ]


def calculate_vwap(rows):

    pv = 0.0
    volume_total = 0

    for x in rows:

        volume = x["volume"]

        if volume <= 0:
            continue

        if x["high"] is not None and x["low"] is not None:

            typical = (
                x["high"]
                + x["low"]
                + x["close"]
            ) / 3

        else:

            typical = x["close"]

        pv += typical * volume
        volume_total += volume

    if volume_total == 0:
        return None

    return pv / volume_total


def average_volume_20(symbol):

    result = chart(
        symbol,
        interval="1d",
        range_="1mo"
    )

    quote = result["indicators"]["quote"][0]

    volumes = quote.get("volume") or []

    clean = [
        float(v)
        for v in volumes
        if v is not None and v > 0
    ]

    if len(clean) > 1:
        clean = clean[:-1]

    clean = clean[-20:]

    if not clean:
        return None

    return sum(clean) / len(clean)


def scan_one(symbol):

    symbol = symbol.strip().upper()

    result = chart(
        symbol,
        interval="1m",
        range_="5d"
    )

    meta = result.get("meta", {})

    all_rows = make_rows(result)

    if not all_rows:
        raise ValueError("분봉 데이터 없음")

    rows = current_trading_day(all_rows)

    if not rows:
        raise ValueError("오늘 분봉 데이터 없음")

    price = float(rows[-1]["close"])

    prev = (
        meta.get("chartPreviousClose")
        or meta.get("previousClose")
    )

    prev = float(prev) if prev else None

    if prev and prev > 0:
        change = ((price / prev) - 1) * 100
    else:
        change = None

    day_volume = int(sum(x["volume"] for x in rows))

    vwap = calculate_vwap(rows)

    avg20 = average_volume_20(symbol)

    if avg20 and avg20 > 0:
        rvol = day_volume / avg20
    else:
        rvol = None

    if vwap is not None:
        above_vwap = price >= vwap
    else:
        above_vwap = None

    return {
        "symbol": symbol,
        "price": round(price, 4),
        "change": round(change, 2) if change is not None else None,
        "volume": day_volume,
        "rvol": round(rvol, 2) if rvol is not None else None,
        "vwap": round(vwap, 4) if vwap is not None else None,
        "above_vwap": above_vwap,
        "updated": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")
    }


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/scan", methods=["POST"])
def scan():

    body = request.get_json(force=True)

    symbols = body.get("symbols", [])
    settings = body.get("settings", {})

    out = []

    for sym in symbols[:30]:

        try:

            x = scan_one(sym)

            min_change = float(settings.get("minChange", 0))
            min_rvol = float(settings.get("minRvol", 0))
            min_volume = int(settings.get("minVolume", 0))
            above_vwap_required = bool(settings.get("aboveVwap", False))

            checks = {
                "상승률":
                    x["change"] is not None
                    and x["change"] >= min_change,

                "RVOL":
                    x["rvol"] is not None
                    and x["rvol"] >= min_rvol,

                "거래량":
                    x["volume"] >= min_volume,

                "VWAP":
                    (not above_vwap_required)
                    or bool(x["above_vwap"])
            }

            x["checks"] = checks
            x["passed"] = all(checks.values())

            out.append(x)

        except Exception as e:

            out.append({
                "symbol": sym.strip().upper(),
                "error": str(e),
                "passed": False
            })

    return jsonify({
        "results": out
    })


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=10000
    )
