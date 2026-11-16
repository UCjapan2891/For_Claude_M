import json

import pandas as pd

from backtest.strategy import Params
from bot.bitbank import sign
from bot.trader import Fill, desired_position, floor_lot, new_state, step

P = Params(entry_n=3, exit_n=2)
T0 = pd.Timestamp("2026-01-01", tz="UTC")


def bars(closes):
    idx = pd.date_range(T0, periods=len(closes), freq="4h")
    c = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({"open": c, "high": c, "low": c, "close": c})


class FakeBroker:
    def __init__(self):
        self.orders = []

    def market(self, pair, side, qty, ref_price):
        self.orders.append((pair, side, round(qty, 4)))
        return Fill(qty, ref_price, 0.0)


def run(state, closes, broker, tmp_path):
    df = bars(closes)
    now = df.index[-1] + pd.Timedelta(minutes=5)  # 最後の足は作りかけ
    return step(state, {"x_jpy": df}, P, broker, now, "paper", tmp_path, tmp_path / "state.json")


def fresh(cash=5000.0, price=1_000_000.0):
    return new_state({"x_jpy": cash}, {"x_jpy": price}, "x_jpy", 0.0)


def test_signature_matches_official_sample():
    assert sign("hoge", "1721121776490", "1000", "/v1/user/assets") == (
        "9ec5745960d05573c8fb047cdd9191bd0c6ede26f07700bb40ecf1a3920abae8"
    )


def test_buys_after_breakout_and_is_idempotent(tmp_path):
    b = FakeBroker()
    closes = [1e6, 1e6, 1e6, 1.1e6, 1.1e6]  # 4本目が確定して買いシグナル
    s = run(fresh(cash=7000.0), closes, b, tmp_path)
    assert b.orders == [("x_jpy", "buy", 0.0049)]  # 上限5,500円/(1.1e6*1.01) を0.0001単位に切り捨て
    run(s, closes, b, tmp_path)  # 同じ足でもう一度動かしても注文しない
    assert len(b.orders) == 1
    assert json.loads((tmp_path / "state.json").read_text())["pairs"]["x_jpy"]["qty"] == 0.0049


def test_order_cap(tmp_path):
    b = FakeBroker()
    run(fresh(cash=50000.0), [1e6, 1e6, 1e6, 1.1e6, 1.1e6], b, tmp_path)
    assert b.orders == [("x_jpy", "buy", 0.0049)]  # 5,500円が上限


def test_missed_runs_do_not_lose_sell_signal():
    df = bars([10, 10, 10, 11, 12, 12, 9, 9.5, 9.5])
    last = df.index[4]  # 5本目まで処理済みで保有中。その後の実行が抜けた
    assert desired_position(df, P, holding=True, last_bar=last) is False


def test_halts_and_sells_below_limit(tmp_path):
    b = FakeBroker()
    s = fresh(cash=7000.0)
    s = run(s, [1e6, 1e6, 1e6, 1.1e6, 1.1e6], b, tmp_path)   # 0.0049 を買う
    s = run(s, [1e6, 1e6, 1e6, 1.1e6, 1.1e6, 0.7e6], b, tmp_path)  # 急落で評価額が6,000円未満
    assert b.orders[-1] == ("x_jpy", "sell", 0.0049)
    assert s["halted"] is True
    run(s, [1e6, 1e6, 1e6, 1.1e6, 1.1e6, 0.7e6, 2e6, 2e6], b, tmp_path)
    assert len(b.orders) == 2  # 停止後は売買しない


def test_floor_lot():
    assert floor_lot(0.00039) == 0.0003
    assert abs(floor_lot(0.0003) - 0.0003) < 1e-12
