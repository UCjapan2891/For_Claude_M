"""枠A のボット。4時間ごとに1回実行する。

  python -m bot.run          仮想売買（注文は出さない）
  python -m bot.run --live   実弾。環境変数 BITBANK_API_KEY / BITBANK_API_SECRET が必要
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd

from backtest.data import bitbank_4h
from backtest.strategy import CRYPTO_4H

from .bitbank import Bitbank, pair_settings
from .trader import LiveBroker, PaperBroker, new_state, save_state, step

RECORDS = Path(__file__).resolve().parent.parent / "records"
BUDGET = {"btc_jpy": 5000.0, "eth_jpy": 5000.0}
HOLD_PAIR = "btc_jpy"  # 比較対象: 開始時に1万円分のBTCを買って放置


def main() -> None:
    live = "--live" in sys.argv
    mode = "live" if live else "paper"
    now = pd.Timestamp.now(tz="UTC")
    years = [now.year - 1, now.year]
    candles = {pair: bitbank_4h(pair, years, refresh=True) for pair in BUDGET}
    fee = {pair: float(pair_settings(pair)["taker_fee_rate_quote"]) for pair in BUDGET}

    state_path = RECORDS / f"crypto_state_{mode}.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
    else:
        prices = {k: float(df["close"].iloc[-1]) for k, df in candles.items()}
        state = new_state(BUDGET, prices, HOLD_PAIR, fee[HOLD_PAIR])
        RECORDS.mkdir(exist_ok=True)
        save_state(state_path, state)

    if live:
        broker = LiveBroker(Bitbank(os.environ["BITBANK_API_KEY"], os.environ["BITBANK_API_SECRET"]))
    else:
        broker = PaperBroker(fee)

    state = step(state, candles, CRYPTO_4H, broker, now, mode, RECORDS, state_path)
    for pair, s in state["pairs"].items():
        print(f"[{mode}] {pair}: 現金 {s['cash']:.0f}円, 保有 {s['qty']}")
    if state["halted"]:
        print("停止中（評価額が6,000円を割った）")


if __name__ == "__main__":
    main()
