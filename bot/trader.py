"""枠A（暗号資産）の売買判断と記録。取引所とのやり取りは Broker に任せる。"""
from __future__ import annotations

import csv
import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from backtest.strategy import Params, signals

BAR = pd.Timedelta(hours=4)
ORDER_CAP_JPY = 5500     # 1回の買い注文の上限
HALT_EQUITY_JPY = 6000   # 枠の評価額がこれを割ったら全部売って停止
BUY_BUFFER = 0.01        # 成行買いで価格が動く分の余裕
LOT = 0.0001


@dataclass
class Fill:
    qty: float
    price: float    # 平均約定価格
    fee_jpy: float


class PaperBroker:
    """仮想売買。直近価格から不利な方向にずらして約定したことにする。"""

    def __init__(self, fee: dict[str, float], slippage: float = 0.0005):
        self.fee, self.slippage = fee, slippage

    def market(self, pair: str, side: str, qty: float, ref_price: float) -> Fill:
        price = ref_price * (1 + self.slippage if side == "buy" else 1 - self.slippage)
        return Fill(qty, price, qty * price * self.fee[pair])


class LiveBroker:
    """bitbank に成行注文を出し、実際の約定内容を返す。"""

    def __init__(self, client):
        self.client = client

    def market(self, pair: str, side: str, qty: float, ref_price: float) -> Fill:
        base = pair.split("_")[0]
        if side == "buy":
            need = qty * ref_price * (1 + BUY_BUFFER)
            if self.client.free_amount("jpy") < need:
                raise RuntimeError(f"日本円の残高不足（必要 {need:.0f}円）")
        elif self.client.free_amount(base) < qty:
            raise RuntimeError(f"{base} の残高不足（必要 {qty}）")
        order_id = self.client.market_order(pair, side, qty)
        for _ in range(10):
            if self.client.order(pair, order_id)["status"] == "FULLY_FILLED":
                break
            time.sleep(1)
        trades = self.client.trades_of(pair, order_id)
        filled = sum(float(t["amount"]) for t in trades)
        if filled <= 0:
            raise RuntimeError(f"注文 {order_id} が約定していない。取引所の画面で確認すること")
        value = sum(float(t["amount"]) * float(t["price"]) for t in trades)
        fee = sum(float(t["fee_amount_quote"]) for t in trades)
        return Fill(filled, value / filled, fee)


def floor_lot(qty: float) -> float:
    return round(math.floor(qty / LOT + 1e-9) * LOT, 4)


def desired_position(df_closed: pd.DataFrame, p: Params, holding: bool, last_bar) -> bool:
    """前回処理した足より後の確定足を順にたどり、持つべきかどうかを返す。

    実行が何回か抜けても、その間の売りシグナルを取りこぼさない。
    """
    sig = signals(df_closed, p)
    if last_bar is not None:
        sig = sig[sig.index > last_bar]
    else:
        sig = sig.tail(1)
    for buy, sell in zip(sig["buy"], sig["sell"]):
        if not holding and buy:
            holding = True
        elif holding and sell:
            holding = False
    return holding


def append_csv(path: Path, row: dict) -> None:
    """1行追記してすぐディスクに書き出す。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)
        f.flush()
        os.fsync(f.fileno())


def save_state(path: Path, state: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def new_state(budget: dict[str, float], prices: dict[str, float], hold_pair: str, fee: float) -> dict:
    """初回の状態。比較用に「開始時に hold_pair を全額買って放置」の数量も決めておく。"""
    total = sum(budget.values())
    q = floor_lot(total / (prices[hold_pair] * (1 + fee)))
    return {
        "halted": False,
        "pairs": {k: {"cash": v, "qty": 0.0, "entry_cost": 0.0, "last_bar": None} for k, v in budget.items()},
        "hold": {"pair": hold_pair, "qty": q, "cash": total - q * prices[hold_pair] * (1 + fee)},
    }


def step(state, candles: dict[str, pd.DataFrame], p: Params, broker, now, mode, records: Path, state_path: Path):
    """1回分の処理。candles は銘柄ごとの4時間足（作りかけの最新足を含んでよい）。"""
    trades_csv = records / f"crypto_trades_{mode}.csv"
    last_price = {k: float(df["close"].iloc[-1]) for k, df in candles.items()}

    def equity() -> float:
        return sum(s["cash"] + s["qty"] * last_price[k] for k, s in state["pairs"].items())

    def trade(pair: str, side: str, qty: float, reason: str) -> None:
        s = state["pairs"][pair]
        fill = broker.market(pair, side, qty, last_price[pair])
        pnl = ""
        if side == "buy":
            cost = fill.qty * fill.price + fill.fee_jpy
            s["cash"] -= cost
            s["qty"] = round(fill.qty, 4)
            s["entry_cost"] = cost
        else:
            proceeds = fill.qty * fill.price - fill.fee_jpy
            pnl = round(proceeds - s["entry_cost"], 2)
            s["cash"] += proceeds
            s["qty"] = floor_lot(s["qty"] - fill.qty)
            s["entry_cost"] = 0.0
        save_state(state_path, state)  # 約定したらすぐ状態を保存
        append_csv(trades_csv, {
            "time": now.isoformat(), "mode": mode, "pair": pair, "side": side, "reason": reason,
            "qty": fill.qty, "price": round(fill.price, 2), "fee_jpy": round(fill.fee_jpy, 2),
            "pnl_jpy": pnl, "cash_after": round(s["cash"], 2),
        })

    if not state["halted"]:
        for pair, df in candles.items():
            s = state["pairs"][pair]
            closed = df[df.index + BAR <= now]
            if closed.empty or (s["last_bar"] and closed.index[-1].isoformat() == s["last_bar"]):
                continue
            last_bar = pd.Timestamp(s["last_bar"]) if s["last_bar"] else None
            holding = s["qty"] > 0
            want = desired_position(closed, p, holding, last_bar)
            if want and not holding:
                budget = min(s["cash"], ORDER_CAP_JPY)
                qty = floor_lot(budget / (last_price[pair] * (1 + BUY_BUFFER)))
                if qty > 0:
                    trade(pair, "buy", qty, "20本高値を上抜け")
            elif holding and not want:
                trade(pair, "sell", s["qty"], "10本安値を下抜け")
            s["last_bar"] = closed.index[-1].isoformat()
            save_state(state_path, state)

        if equity() < HALT_EQUITY_JPY:
            for pair, s in state["pairs"].items():
                if s["qty"] > 0:
                    trade(pair, "sell", s["qty"], "評価額が6,000円を割ったため停止")
            state["halted"] = True
            save_state(state_path, state)

    h = state["hold"]
    append_csv(records / f"crypto_equity_{mode}.csv", {
        "time": now.isoformat(),
        "equity": round(equity(), 2),
        "hold_equity": round(h["cash"] + h["qty"] * last_price[h["pair"]], 2),
        **{f"{k}_qty": s["qty"] for k, s in state["pairs"].items()},
        "halted": state["halted"],
    })
    return state
