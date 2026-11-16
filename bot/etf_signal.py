"""枠B（ETF）のシグナル確認。毎晩1回実行し、翌朝の注文を決める。発注は手動。

  python -m bot.etf_signal [銘柄コード]   既定は 2869.T
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from backtest.data import yahoo_daily
from backtest.strategy import ETF_DAILY, signals

RECORDS = Path(__file__).resolve().parent.parent / "records"


def report(symbol: str, now: pd.Timestamp) -> str:
    df = yahoo_daily(symbol, "6mo", refresh=True)
    # 当日の足は 15:45（大引け後）までは未確定なので使わない
    if df.index[-1].date() == now.date() and now.time() < pd.Timestamp("15:45").time():
        df = df.iloc[:-1]
    sig = signals(df, ETF_DAILY).iloc[-1]
    day, close = df.index[-1], df["close"].iloc[-1]
    high = df["high"].iloc[-ETF_DAILY.entry_n - 1 : -1].max()
    low = df["low"].iloc[-ETF_DAILY.exit_n - 1 : -1].min()
    if sig["buy"]:
        action = "持っていなければ、翌営業日の寄付で買う"
    elif sig["sell"]:
        action = "持っていれば、翌営業日の寄付で売る"
    else:
        action = "何もしない"
    return "\n".join([
        f"# 枠B シグナル（{symbol}）",
        "",
        f"- 判定に使った足: {day:%Y-%m-%d}（終値 {close:,.0f}円）",
        f"- 買いの基準（直近{ETF_DAILY.entry_n}日の高値）: {high:,.0f}円",
        f"- 売りの基準（直近{ETF_DAILY.exit_n}日の安値）: {low:,.0f}円",
        f"- **やること: {action}**",
        "",
        f"更新: {now:%Y-%m-%d %H:%M} JST",
        "",
    ])


if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else "2869.T"
    text = report(symbol, pd.Timestamp.now(tz="Asia/Tokyo"))
    RECORDS.mkdir(exist_ok=True)
    (RECORDS / "etf_signal.md").write_text(text, encoding="utf-8")
    print(text)
