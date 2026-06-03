from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, time as dtime
from pathlib import Path

import requests

from .notifier import ReliableWeChatSender


DEFAULT_REALTIME_CODES = ["600498", "688820", "300803"]


@dataclass(frozen=True)
class Quote:
    code: str
    name: str
    price: float
    open: float
    previous_close: float
    high: float
    low: float
    volume: float
    amount: float
    timestamp: str


@dataclass(frozen=True)
class TradeDecision:
    side: str
    code: str
    name: str
    price: float
    shares: int
    reason: str
    timestamp: str

    def message(self) -> str:
        action = "买入" if self.side == "BUY" else "卖出"
        return (
            f"【A股实时{action}提醒】\n"
            "仅为本地模拟交易，不构成投资建议。\n"
            f"时间：{self.timestamp}\n"
            f"股票：{self.code} {self.name}\n"
            f"{action}价格：{self.price:.2f}\n"
            f"{action}数量：{self.shares}股\n"
            f"触发原因：{self.reason}"
        )


def is_a_share_market_time(now: datetime | None = None) -> bool:
    now = now or datetime.now()
    if now.weekday() >= 5:
        return False
    current = now.time()
    return dtime(9, 30) <= current <= dtime(11, 30) or dtime(13, 0) <= current <= dtime(15, 0)


def market_symbol(code: str) -> str:
    if code.startswith(("5", "6", "9")):
        return "sh" + code
    return "sz" + code


class SinaQuoteProvider:
    def __init__(self, timeout: float = 5.0) -> None:
        self.timeout = timeout

    def fetch(self, codes: list[str]) -> list[Quote]:
        symbols = ",".join(market_symbol(code) for code in codes)
        response = requests.get(
            "https://hq.sinajs.cn/list=" + symbols,
            headers={"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        response.encoding = "gb18030"
        quotes = []
        for symbol, payload in re.findall(r"hq_str_(\w+)=\"([^\"]*)\"", response.text):
            fields = payload.split(",")
            if len(fields) < 32 or not fields[0]:
                continue
            code = symbol[-6:]
            price = _float(fields[3])
            if price <= 0:
                continue
            quotes.append(
                Quote(
                    code=code,
                    name=fields[0],
                    open=_float(fields[1]),
                    previous_close=_float(fields[2]),
                    price=price,
                    high=_float(fields[4]),
                    low=_float(fields[5]),
                    volume=_float(fields[8]),
                    amount=_float(fields[9]),
                    timestamp=f"{fields[30]} {fields[31]}",
                )
            )
        return quotes


class RealtimeDecisionEngine:
    def __init__(
        self,
        *,
        initial_cash: float = 1_000_000,
        max_position_pct: float = 0.20,
        lot_size: int = 100,
        window: int = 5,
        stop_loss_pct: float = 0.04,
        take_profit_pct: float = 0.08,
    ) -> None:
        self.cash = initial_cash
        self.max_position_pct = max_position_pct
        self.lot_size = lot_size
        self.window = window
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.history: dict[str, deque[Quote]] = {}
        self.positions: dict[str, dict[str, float | int | str]] = {}

    def on_quote(self, quote: Quote) -> TradeDecision | None:
        hist = self.history.setdefault(quote.code, deque(maxlen=self.window + 1))
        hist.append(quote)
        if quote.code in self.positions:
            return self._sell_decision(quote)
        return self._buy_decision(quote, list(hist))

    def _buy_decision(self, quote: Quote, hist: list[Quote]) -> TradeDecision | None:
        if len(hist) < self.window + 1:
            return None
        prev_prices = [item.price for item in hist[:-1]]
        avg_price = sum(prev_prices) / len(prev_prices)
        avg_volume = sum(item.volume for item in hist[:-1]) / len(prev_prices)
        momentum = quote.price / avg_price - 1
        volume_ratio = quote.volume / avg_volume if avg_volume > 0 else 0
        intraday_gain = quote.price / quote.previous_close - 1 if quote.previous_close > 0 else 0
        if momentum < 0.015 or volume_ratio < 1.2 or intraday_gain < 0.01:
            return None
        budget = min(self.cash, self.cash * self.max_position_pct)
        shares = int(budget // quote.price // self.lot_size) * self.lot_size
        if shares <= 0:
            return None
        self.cash -= shares * quote.price
        self.positions[quote.code] = {
            "name": quote.name,
            "shares": shares,
            "buy_price": quote.price,
            "highest_price": quote.price,
        }
        return TradeDecision(
            side="BUY",
            code=quote.code,
            name=quote.name,
            price=quote.price,
            shares=shares,
            reason=f"短周期动量{momentum * 100:.2f}%，量比{volume_ratio:.2f}，日内涨幅{intraday_gain * 100:.2f}%",
            timestamp=quote.timestamp,
        )

    def _sell_decision(self, quote: Quote) -> TradeDecision | None:
        pos = self.positions[quote.code]
        pos["highest_price"] = max(float(pos["highest_price"]), quote.price)
        buy_price = float(pos["buy_price"])
        drawdown = quote.price / float(pos["highest_price"]) - 1
        ret = quote.price / buy_price - 1
        reason = ""
        if ret <= -self.stop_loss_pct:
            reason = f"止损触发，收益率{ret * 100:.2f}%"
        elif ret >= self.take_profit_pct:
            reason = f"止盈触发，收益率{ret * 100:.2f}%"
        elif drawdown <= -0.03:
            reason = f"移动止盈触发，高点回撤{drawdown * 100:.2f}%"
        if not reason:
            return None
        shares = int(pos["shares"])
        self.cash += shares * quote.price
        del self.positions[quote.code]
        return TradeDecision(
            side="SELL",
            code=quote.code,
            name=quote.name,
            price=quote.price,
            shares=shares,
            reason=reason,
            timestamp=quote.timestamp,
        )


def run_realtime_monitor(
    *,
    codes: list[str],
    provider: SinaQuoteProvider,
    sender: ReliableWeChatSender,
    poll_seconds: float = 1.0,
    state_log: Path | None = None,
) -> None:
    engine = RealtimeDecisionEngine()
    while True:
        if not is_a_share_market_time():
            time.sleep(min(60, max(1, poll_seconds)))
            continue
        flushed = sender.flush_outbox()
        if state_log is not None and (flushed.sent or flushed.failed):
            state_log.parent.mkdir(parents=True, exist_ok=True)
            state_log.write_text(f"outbox sent={flushed.sent} failed={flushed.failed}\n", encoding="utf-8")
        for quote in provider.fetch(codes):
            decision = engine.on_quote(quote)
            if decision is not None:
                sender.send_or_queue(decision.message(), kind="realtime_trade")
        time.sleep(poll_seconds)


def _float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
