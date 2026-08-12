from flask import Flask, render_template, request, jsonify
import yfinance as yf
import pandas as pd

app = Flask(__name__)

DEFAULT_SETTINGS = {
    "min_change_pct": 10.0,
    "min_rvol": 3.0,
    "min_volume": 1_000_000,
    "require_vwap": True,
    "stop_loss_pct": 3.0,
    "target1_pct": 5.0,
    "target2_pct": 10.0,
}

def analyze_symbol(symbol, settings):
    symbol = symbol.upper().strip()
    if not symbol:
        return None

    ticker = yf.Ticker(symbol)
    intraday = ticker.history(period="5d", interval="1m", auto_adjust=False, prepost=True)
    daily = ticker.history(period="10d", interval="1d", auto_adjust=False)

    if intraday is None or intraday.empty or daily is None or len(daily) < 2:
        return {"symbol": symbol, "error": "시세 데이터를 불러오지 못했습니다."}

    intraday = intraday.dropna(subset=["Close"]).copy()
    dates = pd.Series(intraday.index.date, index=intraday.index)
    unique_dates = list(dict.fromkeys(dates.tolist()))
    if not unique_dates:
        return {"symbol": symbol, "error": "당일 데이터가 없습니다."}

    today_date = unique_dates[-1]
    today = intraday[dates == today_date].copy()
    if today.empty:
        return {"symbol": symbol, "error": "당일 데이터가 없습니다."}

    price = float(today["Close"].iloc[-1])
    prev_close = float(daily["Close"].iloc[-2])
    change_pct = (price / prev_close - 1.0) * 100.0 if prev_close > 0 else 0.0

    volumes = today["Volume"].fillna(0)
    day_volume = int(volumes.sum())

    typical = (today["High"] + today["Low"] + today["Close"]) / 3.0
    if day_volume > 0:
        vwap = float((typical * volumes).sum() / day_volume)
    else:
        vwap = price

    n_today = len(today)
    historical_cum = []
    for d in unique_dates[:-1]:
        day = intraday[dates == d]
        if day.empty:
            continue
        sample = day.iloc[:min(n_today, len(day))]
        historical_cum.append(float(sample["Volume"].fillna(0).sum()))

    if historical_cum:
        avg_hist = sum(historical_cum) / len(historical_cum)
        rvol = day_volume / avg_hist if avg_hist > 0 else 0.0
    else:
        rvol = 0.0

    signal = (
        change_pct >= settings["min_change_pct"]
        and rvol >= settings["min_rvol"]
        and day_volume >= settings["min_volume"]
        and ((price >= vwap) if settings["require_vwap"] else True)
    )

    stop = price * (1 - settings["stop_loss_pct"]/100)
    t1 = price * (1 + settings["target1_pct"]/100)
    t2 = price * (1 + settings["target2_pct"]/100)

    return {
        "symbol": symbol,
        "price": round(price, 4),
        "change_pct": round(change_pct, 2),
        "volume": day_volume,
        "rvol": round(rvol, 2),
        "vwap": round(vwap, 4),
        "stop": round(stop, 4),
        "target1": round(t1, 4),
        "target2": round(t2, 4),
        "signal": signal,
    }

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/scan", methods=["POST"])
def scan():
    data = request.get_json(force=True)
    symbols = data.get("symbols", [])
    settings = DEFAULT_SETTINGS.copy()
    settings.update(data.get("settings", {}))

    cleaned = []
    for s in symbols:
        s = str(s).upper().strip()
        if s and s not in cleaned:
            cleaned.append(s)

    cleaned = cleaned[:20]
    results = []
    for symbol in cleaned:
        try:
            results.append(analyze_symbol(symbol, settings))
        except Exception as e:
            results.append({"symbol": symbol, "error": str(e)})

    return jsonify({"results": results, "settings": settings})

@app.route("/health")
def health():
    return {"ok": True}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
