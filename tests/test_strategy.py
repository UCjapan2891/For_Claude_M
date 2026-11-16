import pandas as pd

from backtest.strategy import Costs, Params, buy_and_hold, max_drawdown, signals, simulate

FREE = Costs(fee=0.0, slippage=0.0, lot=1.0)


def bars(closes):
    idx = pd.date_range("2026-01-01", periods=len(closes), freq="D")
    c = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({"open": c, "high": c, "low": c, "close": c})


def test_buy_signal_uses_only_previous_bars():
    df = bars([10, 10, 10, 11, 11])
    s = signals(df, Params(entry_n=3, exit_n=2))
    assert list(s["buy"]) == [False, False, False, True, False]


def test_sell_signal_on_break_of_previous_lows():
    df = bars([10, 10, 9, 9])
    s = signals(df, Params(entry_n=3, exit_n=2))
    assert list(s["sell"]) == [False, False, True, False]


def test_trade_executes_at_next_open():
    # 4本目で買いシグナル → 5本目の始値(12)で買い。7本目で売りシグナル → 8本目の始値(8)で売り
    df = bars([10, 10, 10, 11, 12, 12, 9, 8, 8])
    eq, trades = simulate(df, Params(entry_n=3, exit_n=2), cash=120, costs=FREE)
    assert len(trades) == 1
    t = trades.iloc[0]
    assert (t.entry_price, t.exit_price, t.qty) == (12, 8, 10)
    assert t.pnl == -40
    assert eq.iloc[-1] == 80


def test_fee_and_lot_rounding():
    df = bars([10, 10, 10, 11, 12, 12, 12])
    eq, _ = simulate(df, Params(3, 2), cash=100, costs=Costs(fee=0.01, slippage=0.0, lot=1.0))
    # 12*1.01=12.12 → 8単位、残り 100-96.96=3.04
    assert abs(eq.iloc[-1] - (3.04 + 8 * 12)) < 1e-9


def test_buy_and_hold_and_drawdown():
    df = bars([10, 20, 10])
    eq = buy_and_hold(df, 100, FREE)
    assert list(eq) == [100, 200, 100]
    assert max_drawdown(eq) == -0.5
