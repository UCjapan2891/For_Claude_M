"""枠A（暗号資産）と枠B（ETF）のバックテスト。

使い方: python -m backtest.run [--refresh]
全期間の成績と、「13週間だけ運用した場合」を1週間ずつずらして繰り返した結果を出す。
"""
from __future__ import annotations

import sys

import pandas as pd

from .data import bitbank_4h, yahoo_daily
from .strategy import CRYPTO_4H, ETF_DAILY, Costs, buy_and_hold, max_drawdown, simulate

# 手数料は bitbank の公開API（/v1/spot/pairs）で 2026/11/16 に確認したテイカー料率。ずれは仮定
BTC_COSTS = Costs(fee=0.0010, slippage=0.0005, lot=0.0001)
ETH_COSTS = Costs(fee=0.0012, slippage=0.0005, lot=0.0001)
ETF_COSTS = Costs(fee=0.0, slippage=0.001, lot=1.0)      # 2869 は1口単位
ETF10_COSTS = Costs(fee=0.0, slippage=0.001, lot=10.0)   # 1579 は10口単位

WINDOW = pd.Timedelta(weeks=13)
STEP = pd.Timedelta(weeks=1)
MIN_TRADES = 10  # 判定基準の取引回数


def full_period(name, df, p, cash, costs):
    eq, trades = simulate(df, p, cash, costs)
    bh = buy_and_hold(df, cash, costs)
    n = len(trades)
    win = (trades["pnl"] > 0).mean() if n else float("nan")
    return {
        "対象": name,
        "期間": f"{df.index[0]:%Y-%m-%d}〜{df.index[-1]:%Y-%m-%d}",
        "戦略": f"{eq.iloc[-1] / cash - 1:+.1%}",
        "放置": f"{bh.iloc[-1] / cash - 1:+.1%}",
        "戦略の最大下落": f"{max_drawdown(eq):.1%}",
        "放置の最大下落": f"{max_drawdown(bh):.1%}",
        "取引回数": n,
        "勝率": f"{win:.0%}",
    }


def rolling_windows(df, p, cash, costs):
    """13週間の運用を、開始日を1週間ずつずらして繰り返す。"""
    rows = []
    start = df.index[0] + pd.Timedelta(days=30)  # シグナル計算用の助走
    while start + WINDOW <= df.index[-1]:
        warm = df[df.index < start].tail(p.entry_n + 1)
        win = df[(df.index >= start) & (df.index < start + WINDOW)]
        eq, trades = simulate(pd.concat([warm, win]), p, cash, costs)
        bh = buy_and_hold(win, cash, costs)
        rows.append(
            {
                "start": start,
                "strategy": eq.iloc[-1] / cash - 1,
                "hold": bh.iloc[-1] / cash - 1,
                "trades": len(trades),
                "min_equity": eq.min() / cash,
            }
        )
        start += STEP
    return pd.DataFrame(rows)


def window_summary(name, w):
    return {
        "対象": name,
        "試行数": len(w),
        "戦略の中央値": f"{w['strategy'].median():+.1%}",
        "放置の中央値": f"{w['hold'].median():+.1%}",
        "戦略の最悪": f"{w['strategy'].min():+.1%}",
        "放置の最悪": f"{w['hold'].min():+.1%}",
        "放置に勝った割合": f"{(w['strategy'] > w['hold']).mean():.0%}",
        "利益が出た割合": f"{(w['strategy'] > 0).mean():.0%}",
        "取引回数の中央値": int(w["trades"].median()),
        f"取引{MIN_TRADES}回以上の割合": f"{(w['trades'] >= MIN_TRADES).mean():.0%}",
        "-40%で打ち切りの割合": f"{(w['min_equity'] <= 0.6).mean():.0%}",
    }


def main():
    refresh = "--refresh" in sys.argv
    years = list(range(2021, pd.Timestamp.now().year + 1))
    targets = [
        ("A: BTC/JPY 4時間足", bitbank_4h("btc_jpy", years, refresh), CRYPTO_4H, 5000, BTC_COSTS),
        ("A: ETH/JPY 4時間足", bitbank_4h("eth_jpy", years, refresh), CRYPTO_4H, 5000, ETH_COSTS),
        ("B: 2869 日足", yahoo_daily("2869.T", "5y", refresh), ETF_DAILY, 10000, ETF_COSTS),
        ("B予備: 1579 日足", yahoo_daily("1579.T", "5y", refresh), ETF_DAILY, 10000, ETF10_COSTS),
    ]
    full = [full_period(*t) for t in targets]
    wins = [window_summary(t[0], rolling_windows(*t[1:])) for t in targets]
    pd.set_option("display.unicode.east_asian_width", True, "display.width", 250)
    print("■ 全期間")
    print(pd.DataFrame(full).to_string(index=False))
    print("\n■ 13週間だけ運用した場合（開始日を1週間ずつずらして繰り返し）")
    print(pd.DataFrame(wins).set_index("対象").T.to_string())


if __name__ == "__main__":
    main()
