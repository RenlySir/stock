from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

import requests

from .notifier import ReliableWeChatSender
from .market_calendar import is_a_share_trading_time


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


class QuoteProvider(Protocol):
    name: str

    def fetch(self, codes: list[str]) -> list[Quote]:
        ...


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
    return is_a_share_trading_time(now)


def market_symbol(code: str) -> str:
    if code.startswith(("5", "6", "9")):
        return "sh" + code
    return "sz" + code


class SinaQuoteProvider:
    name = "sina"

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


class EastMoneyQuoteProvider:
    name = "eastmoney"

    def __init__(self, timeout: float = 5.0) -> None:
        self.timeout = timeout

    def fetch(self, codes: list[str]) -> list[Quote]:
        response = requests.get(
            "https://push2.eastmoney.com/api/qt/ulist.np/get",
            params={
                "fltt": "2",
                "invt": "2",
                "fields": "f12,f14,f2,f5,f6,f17,f18,f15,f16,f13,f124",
                "secids": ",".join(_eastmoney_symbol(code) for code in codes),
            },
            headers={"Referer": "https://quote.eastmoney.com/", "User-Agent": "Mozilla/5.0"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("eastmoney malformed response")
        if int(payload.get("rc", -1)) != 0:
            raise RuntimeError(f"eastmoney rc={payload.get('rc')}")
        data = payload.get("data")
        if data is not None and not isinstance(data, dict):
            raise RuntimeError("eastmoney malformed response")
        rows = data.get("diff", []) if isinstance(data, dict) else []
        if not isinstance(rows, list):
            raise RuntimeError("eastmoney malformed response")
        quotes = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            price = _float(row.get("f2"))
            code = code6(row.get("f12"))
            if price <= 0 or not code:
                continue
            quotes.append(
                Quote(
                    code=code,
                    name=str(row.get("f14") or code),
                    price=price,
                    open=_float(row.get("f17")),
                    previous_close=_float(row.get("f18")),
                    high=_float(row.get("f15")),
                    low=_float(row.get("f16")),
                    volume=_float(row.get("f5")) * 100,
                    amount=_float(row.get("f6")),
                    timestamp=_format_eastmoney_timestamp(row.get("f124")),
                )
            )
        return quotes


class CombinedQuoteProvider:
    name = "combined"

    def __init__(self, providers: list[QuoteProvider]) -> None:
        if not providers:
            raise ValueError("providers must not be empty")
        self.providers = providers

    def fetch(self, codes: list[str], state_log: Path | None = None) -> list[Quote]:
        errors: list[str] = []
        expected_codes = [code6(code) for code in codes if code6(code)]
        collected: dict[str, Quote] = {}
        for provider in self.providers:
            missing_codes = [code for code in expected_codes if code not in collected]
            if not missing_codes:
                break
            try:
                quotes = provider.fetch(missing_codes)
            except Exception as exc:
                message = f"quote provider failed provider={provider.name} error={type(exc).__name__}: {exc}"
                errors.append(message)
                _append_state_log(state_log, message)
                continue
            usable_quotes = [quote for quote in quotes if quote.code in missing_codes]
            for quote in usable_quotes:
                collected.setdefault(quote.code, quote)
            still_missing = [code for code in expected_codes if code not in collected]
            if usable_quotes and not still_missing:
                message = (
                    f"quote provider ok provider={provider.name} count={len(usable_quotes)}"
                    if len(collected) == len(usable_quotes)
                    else f"quote provider filled provider={provider.name} count={len(usable_quotes)} total={len(collected)}"
                )
                _append_state_log(state_log, message)
                break
            if usable_quotes:
                message = f"quote provider partial provider={provider.name} count={len(usable_quotes)} missing={','.join(still_missing)}"
                errors.append(message)
                _append_state_log(state_log, message)
                continue
            message = f"quote provider empty provider={provider.name}"
            errors.append(message)
            _append_state_log(state_log, message)
        if collected:
            return [collected[code] for code in expected_codes if code in collected]
        raise RuntimeError("; ".join(errors) if errors else "no quote provider returned data")


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


def poll_realtime_once(
    *,
    codes: list[str],
    provider: QuoteProvider,
    sender: ReliableWeChatSender,
    engine: RealtimeDecisionEngine,
    state_log: Path | None = None,
) -> None:
    try:
        if isinstance(provider, CombinedQuoteProvider):
            quotes = provider.fetch(codes, state_log=state_log)
        else:
            quotes = provider.fetch(codes)
    except Exception as exc:
        _append_state_log(state_log, f"quote fetch error: {type(exc).__name__}: {exc}")
        return
    found_codes = {quote.code for quote in quotes}
    expected_codes = [str(code).zfill(6) for code in codes]
    missing = [code for code in expected_codes if code not in found_codes]
    if missing:
        _append_state_log(
            state_log,
            f"quote fetch partial count={len(quotes)} expected={len(expected_codes)} missing={','.join(missing)}",
        )
    else:
        latest = max((quote.timestamp for quote in quotes), default="")
        _append_state_log(state_log, f"quote fetch ok count={len(quotes)} latest={latest}")
    for quote in quotes:
        decision = engine.on_quote(quote)
        if decision is not None:
            sender.send_or_queue(decision.message(), kind="realtime_trade")


def run_realtime_monitor(
    *,
    codes: list[str],
    provider: QuoteProvider,
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
        poll_realtime_once(codes=codes, provider=provider, sender=sender, engine=engine, state_log=state_log)
        time.sleep(poll_seconds)


def _float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def code6(value: object) -> str:
    text = str(value or "").strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text.zfill(6) if text else ""


def _eastmoney_symbol(code: str) -> str:
    code = str(code).zfill(6)
    market = "1" if code.startswith(("5", "6", "9")) else "0"
    return f"{market}.{code}"


def _format_eastmoney_timestamp(value: object) -> str:
    try:
        return datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _append_state_log(path: Path | None, message: str) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{now} {message}\n")
