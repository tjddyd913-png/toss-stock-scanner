from flask import Flask, render_template, request, jsonify
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

app = Flask(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json,text/plain,*/*"
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
        timeout=15
    )

    r.raise_for_status()

    data = r.json()

    if data.get("chart", {}).get("error"):
        raise ValueError(
            str(data["chart"]["error"])
        )

    result = data.get("chart", {}).get("result")

    if not result:
        raise ValueError("Yahoo 시세 데이터 없음")

    return result[0]


def make_rows(result):

    timestamps = result.get("timestamp") or []

    indicators = result.get("indicators", {})
    quotes = indicators.get("quote") or []

    if not quotes:
        return []

    q = quotes[0]

    opens = q.get("open") or []
    highs = q.get("high") or []
    lows = q.get("low") or []
    closes = q.get("close") or []
    volumes = q.get("volume") or []

    rows = []

    for i, timestamp in enumerate(timestamps):

        if i >= len(closes):
            continue

        close = closes[i]

        if close is None:
            continue

        dt = datetime.fromtimestamp(timestamp, NY)

        rows.append({
            "timestamp": timestamp,
            "dt": dt,
            "open": opens[i] if i < len(opens) else None,
            "high": highs[i] if i < len(highs) else None,
            "low": lows[i] if i < len(lows) else None,
            "close": close,
            "volume": (
                volumes[i]
                if i < len(volumes)
                and volumes[i] is not None
                else 0
            )
        })

    return rows


def current_trading_day_rows(rows):

    if not rows:
        return []

    # 가장 최근 데이터가 존재하는 미국 날짜
    latest_date = rows[-1]["dt"].date()

    return [
        x for x in rows
        if x["dt"].date() == latest_date
    ]


def latest_price(rows, meta):

    #
    # Yahoo meta regularMarketPrice는
    # 데이마켓/시간외 가격이 늦을 수 있으므로
    # 최신 분봉 close를 우선 사용
    #

    if rows:
        last_close = rows[-1].get("close")

        if last_close is not None:
            return float(last_close)

    price = meta.get("regularMarketPrice")

    if price is not None:
        return float(price)

    raise ValueError("현재가 없음")


def previous_close(meta):

    candidates = [
        meta.get("chartPreviousClose"),
        meta.get("previousClose")
    ]

    for value in candidates:

        if value is not None:

            try:
                return float(value)
            except:
                pass

    return None


def calculate_vwap(rows):

    pv = 0.0
    volume_sum = 0

    for x in rows:

        volume = x.get("volume") or 0

        if volume <= 0:
            continue

        high = x.get("high")
        low = x.get("low")
        close = x.get("close")

        if close is None:
            continue

        if high is not None and low is not None:

            typical = (
                float(high)
                + float(low)
                + float(close)
            ) / 3

        else:

            typical = float(close)

        pv += typical * volume
        volume_sum += volume

    if volume_sum == 0:
        return None

    return pv / volume_sum


def average_volume_20(symbol):

    result = chart(
        symbol,
        "1d",
        "1mo"
    )

    q = result["indicators"]["quote"][0]

    volumes = q.get("volume") or []

    clean = []

    for v in volumes:

        if v is None:
            continue

        try:
            v = float(v)

            if v > 0:
                clean.append(v)

        except:
            pass

    #
    # 오늘 데이터가 포함될 가능성이 있으므로
    # 마지막 값 제외
    #

    if len(clean) > 1:
        history = clean[:-1][-20:]
    else:
        history = []

    if not history:
        return None

    return sum(history) / len(history)


def scan_one(symbol):

    symbol = symbol.strip().upper()

    if not symbol:
        raise ValueError("티커 없음")

    result = chart(
        symbol,
        "1m",
        "5d"
    )

    meta = result.get("meta", {})

    all_rows = make_rows(result)

    if not all_rows:
        raise ValueError("분봉 데이터 없음")

    rows = current_trading_day_rows(all_rows)

    if not rows:
        raise ValueError("오늘 분봉 데이터 없음")

    # --------------------------------
    # 현재가
    # --------------------------------

    price = latest_price(
        rows,
        meta
    )

    # --------------------------------
    # 전일 종가
    # --------------------------------

    prev = previous_close(meta)

    change = None

    if prev and prev > 0:

        change = (
            (price / prev) - 1
        ) * 100

    # --------------------------------
    # 당일 누적 거래량
    # --------------------------------

    day_volume = int(
        sum(
            int(x.get("volume") or 0)
            for x in rows
        )
    )

    # Yahoo meta 거래량과 비교
    meta_volume = meta.get("regularMarketVolume")

    try:

        if meta_volume is not None:

            meta_volume = int(meta_volume)

            #
            # 정규장에서는 meta 거래량이
            # 더 정확할 수 있음
            #

            if meta_volume > day_volume:
                day_volume = meta_volume

    except:
        pass

    # --------------------------------
    # VWAP
    # --------------------------------

    vwap = calculate_vwap(rows)

    # --------------------------------
    # RVOL
    # --------------------------------

    avg20 = average_volume_20(symbol)

    rvol = None

    if avg20 and avg20 > 0:

        rvol = (
            day_volume / avg20
        )

    # --------------------------------
    # VWAP 위치
    # --------------------------------

    above_vwap = None

    if vwap is not None:

        above_vwap = (
            price >= vwap
        )

    # 최신 데이터 시간

    last_dt = rows[-1]["dt"]

    return {

        "symbol": symbol,

        "price": round(price, 4),

        "change": (
            round(change, 2)
            if change is not None
            else None
        ),

        "volume": day_volume,

        "rvol": (
            round(rvol, 2)
            if rvol is not None
            else None
        ),

        "vwap": (
            round(vwap, 4)
            if vwap is not None
            else None
        ),

        "above_vwap": above_vwap,

        "market_data_time":
            last_dt.astimezone(KST).strftime(
                "%Y-%m-%d %H:%M:%S KST"
            ),

        "updated":
            datetime.now(KST).strftime(
                "%Y-%m-%d %H:%M:%S KST"
            )
    }


@app.route("/")
def home():

    return render_template(
        "index.html"
    )


@app.route(
    "/api/scan",
    methods=["POST"]
)
def scan():

    body = request.get_json(
        force=True
    )

    symbols = body.get(
        "symbols",
        []
    )

    settings = body.get(
        "settings",
        {}
    )

    output = []

    for sym in symbols[:30]:

        try:

            x = scan_one(sym)

            min_change = float(
                settings.get(
                    "minChange",
                    0
                )
            )

            min_rvol = float(
                settings.get(
                    "minRvol",
                    0
                )
            )

            min_volume = int(
                settings.get(
                    "minVolume",
                    0
                )
            )

            require_vwap = bool(
                settings.get(
                    "aboveVwap",
                    False
                )
            )

            checks = {

                "상승률":
                    x["change"] is not None
                    and
                    x["change"] >= min_change,

                "RVOL":
                    x["rvol"] is not None
                    and
                    x["rvol"] >= min_rvol,

                "거래량":
                    x["volume"]
                    >= min_volume,

                "VWAP":
                    (
                        not require_vwap
                    )
                    or
                    (
                        x["above_vwap"]
                        is True
                    )
            }

            x["checks"] = checks

            x["passed"] = all(
                checks.values()
            )

            output.append(x)

        except Exception as e:

            output.append({

                "symbol":
                    str(sym).upper(),

                "error":
                    str(e),

                "passed":
                    False
            })

    return jsonify({
        "results": output
    })


if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=10000
    )
