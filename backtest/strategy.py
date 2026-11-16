"""売買ルール（純粋ロジック）。バックテストとボットの両方から使う。

ルール: ドンチャン・ブレイクアウト
  買い: 確定した足の終値が、その前の entry_n 本の高値の最大を上回る
  売り: 確定した足の終値が、その前の exit_n 本の安値の最小を下回る
シグナルは足の確定時に出し、発注は次の足の始値で行う。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Params:
    entry_n: int  # 買い判定に使う過去の本数
    exit_n: int   # 売り判定に使う過去の本数


CRYPTO_4H = Params(entry_n=20, exit_n=10)
ETF_DAILY = Params(entry_n=10, exit_n=5)


def signals(df: pd.DataFrame, p: Params) -> pd.DataFrame:
    """各足の確定時点のシグナルを返す。df は open/high/low/close を持つ。"""
    prev_high = df["high"].shift(1).rolling(p.entry_n).max()
    prev_low = df["low"].shift(1).rolling(p.exit_n).min()
    return pd.DataFrame(
        {"buy": df["close"] > prev_high, "sell": df["close"] < prev_low},
        index=df.index,
    )


@dataclass(frozen=True)
class Costs:
    fee: float       # 約定代金に対する手数料率
    slippage: float  # 始値からの不利なずれ（率）
    lot: float       # 最小売買単位（数量）


def simulate(df: pd.DataFrame, p: Params, cash: float, costs: Costs):
    """全額買い・全額売りで運用した結果を返す。

    戻り値: (資産推移 Series, 取引一覧 DataFrame)
    資産は各足の終値で評価する。
    """
    sig = signals(df, p)
    opens = df["open"].to_numpy()
    closes = df["close"].to_numpy()
    buy = sig["buy"].to_numpy()
    sell = sig["sell"].to_numpy()

    qty = 0.0
    equity = np.empty(len(df))
    trades = []
    entry = None
    for i in range(len(df)):
        if i > 0:
            if qty == 0 and buy[i - 1]:
                price = opens[i] * (1 + costs.slippage)
                q = np.floor(cash / (price * (1 + costs.fee)) / costs.lot) * costs.lot
                if q > 0:
                    cash -= q * price * (1 + costs.fee)
                    qty = q
                    entry = (df.index[i], price, q)
            elif qty > 0 and sell[i - 1]:
                price = opens[i] * (1 - costs.slippage)
                cash += qty * price * (1 - costs.fee)
                cost_in = entry[1] * entry[2] * (1 + costs.fee)
                trades.append(
                    {
                        "entry_time": entry[0],
                        "exit_time": df.index[i],
                        "entry_price": entry[1],
                        "exit_price": price,
                        "qty": entry[2],
                        "pnl": qty * price * (1 - costs.fee) - cost_in,
                    }
                )
                qty = 0.0
                entry = None
        equity[i] = cash + qty * closes[i]
    return pd.Series(equity, index=df.index), pd.DataFrame(trades)


def buy_and_hold(df: pd.DataFrame, cash: float, costs: Costs) -> pd.Series:
    """最初の足の始値で買って放置した場合の資産推移。"""
    price = df["open"].iloc[0] * (1 + costs.slippage)
    q = np.floor(cash / (price * (1 + costs.fee)) / costs.lot) * costs.lot
    rest = cash - q * price * (1 + costs.fee)
    return rest + q * df["close"]


def max_drawdown(equity: pd.Series) -> float:
    """最大下落率（負の値）。"""
    return float((equity / equity.cummax() - 1).min())
