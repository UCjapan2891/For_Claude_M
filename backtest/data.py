"""価格データの取得。取得結果は data/ にキャッシュする（git には入れない）。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import requests

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
UA = {"User-Agent": "Mozilla/5.0"}

# Yahoo の日足は分割前後の調整が崩れている（分割前が未調整、分割直後に二重調整の日がある）。
# 確認できた分割だけここに書き、自前で現在の価格水準にそろえる。 銘柄: (権利落ち日, 分割比率)
SPLITS = {"2869.T": ("2026-07-03", 25), "1579.T": ("2024-06-28", 100)}


def fix_split(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if symbol not in SPLITS:
        return df
    date, ratio = SPLITS[symbol]
    ex = pd.Timestamp(date, tz=df.index.tz)
    cols = ["open", "high", "low", "close"]
    df = df.copy()
    df.loc[df.index < ex, cols] /= ratio
    # 二重調整された日を戻す（前日終値の1/5未満なら異常とみなす）
    after = df.index[(df.index >= ex) & (df.index <= ex + pd.Timedelta(days=10))]
    for t in after:
        prev = df["close"].shift(1).loc[t]
        if df.loc[t, "close"] < prev / 5:
            df.loc[t, cols] *= ratio
    return df


def bitbank_4h(pair: str, years: list[int], refresh: bool = False) -> pd.DataFrame:
    """bitbank の公開APIから4時間足を取得する。pair 例: 'btc_jpy'"""
    cache = DATA_DIR / f"bitbank_{pair}_4h_{years[0]}_{years[-1]}.csv"
    if cache.exists() and not refresh:
        return pd.read_csv(cache, index_col=0, parse_dates=True)
    rows = []
    for y in years:
        url = f"https://public.bitbank.cc/{pair}/candlestick/4hour/{y}"
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        body = r.json()
        if body.get("success") != 1:
            continue  # その年のデータが無い
        rows += body["data"]["candlestick"][0]["ohlcv"]
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume", "ts"])
    df.index = pd.to_datetime(df.pop("ts"), unit="ms", utc=True)
    df = df.astype(float).sort_index()
    df = df[~df.index.duplicated()]
    DATA_DIR.mkdir(exist_ok=True)
    df.to_csv(cache)
    return df


def yahoo_daily(symbol: str, range_: str = "5y", refresh: bool = False) -> pd.DataFrame:
    """Yahoo Finance から日足を取得する。symbol 例: '2869.T'

    分割は SPLITS の登録に基づいて現在の価格水準にそろえる。
    """
    cache = DATA_DIR / f"yahoo_{symbol}_1d_{range_}.csv"
    if cache.exists() and not refresh:
        return pd.read_csv(cache, index_col=0, parse_dates=True)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    r = requests.get(url, params={"range": range_, "interval": "1d"}, headers=UA, timeout=30)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    df = pd.DataFrame(
        {k: q[k] for k in ["open", "high", "low", "close", "volume"]},
        index=pd.to_datetime(res["timestamp"], unit="s", utc=True).tz_convert("Asia/Tokyo").normalize(),
    ).dropna()
    df = fix_split(df, symbol)
    worst = df["close"].pct_change().abs().max()
    if worst > 0.5:
        raise ValueError(f"{symbol}: 1日で{worst:.0%}動いた日がある。未登録の分割の可能性")
    DATA_DIR.mkdir(exist_ok=True)
    df.to_csv(cache)
    return df
