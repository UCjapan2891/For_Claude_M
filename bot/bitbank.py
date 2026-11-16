"""bitbank の REST API クライアント（現物のみ）。

仕様: https://github.com/bitbankinc/bitbank-api-docs/blob/master/rest-api.md
APIキーは環境変数から読む。出金権限なしで発行すること。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import requests

BASE = "https://api.bitbank.cc"
TIME_WINDOW = "5000"


def sign(secret: str, request_time: str, window: str, payload: str) -> str:
    """ACCESS-TIME-WINDOW 方式の署名。payload は GET ならパス＋クエリ、POST なら本文。"""
    msg = f"{request_time}{window}{payload}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


class BitbankError(RuntimeError):
    pass


class Bitbank:
    def __init__(self, key: str, secret: str):
        self._key = key
        self._secret = secret

    def _headers(self, payload: str) -> dict:
        t = str(int(time.time() * 1000))
        return {
            "ACCESS-KEY": self._key,
            "ACCESS-REQUEST-TIME": t,
            "ACCESS-TIME-WINDOW": TIME_WINDOW,
            "ACCESS-SIGNATURE": sign(self._secret, t, TIME_WINDOW, payload),
            "Content-Type": "application/json",
        }

    @staticmethod
    def _unwrap(r: requests.Response) -> dict:
        body = r.json()
        if body.get("success") != 1:
            raise BitbankError(f"bitbank エラー: {body.get('data')}")
        return body["data"]

    def _get(self, path: str, params: dict | None = None) -> dict:
        full = f"/v1{path}" + (f"?{urlencode(params)}" if params else "")
        return self._unwrap(requests.get(BASE + full, headers=self._headers(full), timeout=30))

    def _post(self, path: str, body: dict) -> dict:
        raw = json.dumps(body)
        return self._unwrap(
            requests.post(f"{BASE}/v1{path}", data=raw, headers=self._headers(raw), timeout=30)
        )

    def free_amount(self, asset: str) -> float:
        for a in self._get("/user/assets")["assets"]:
            if a["asset"] == asset:
                return float(a["free_amount"])
        return 0.0

    def market_order(self, pair: str, side: str, amount: float) -> int:
        body = {"pair": pair, "amount": f"{amount:.4f}", "side": side, "type": "market"}
        return self._post("/user/spot/order", body)["order_id"]

    def order(self, pair: str, order_id: int) -> dict:
        return self._get("/user/spot/order", {"pair": pair, "order_id": order_id})

    def trades_of(self, pair: str, order_id: int) -> list[dict]:
        return self._get("/user/spot/trade_history", {"pair": pair, "order_id": order_id})["trades"]


def pair_settings(pair: str) -> dict:
    """公開の銘柄設定（手数料率、最小数量）。"""
    r = requests.get(f"{BASE}/v1/spot/pairs", timeout=30)
    for p in Bitbank._unwrap(r)["pairs"]:
        if p["name"] == pair:
            return p
    raise BitbankError(f"銘柄が見つからない: {pair}")
