from __future__ import annotations

import math

import pandas as pd


REQUIRED_COLUMNS = {"date", "code", "open", "high", "low", "close", "volume", "amount"}


def code6(value: object) -> str:
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text.zfill(6)


def load_market_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"code": str})
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"missing required columns: {', '.join(sorted(missing))}")
    return normalize_bars(df)


def normalize_bars(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["code"] = out["code"].map(code6)
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    if "name" not in out.columns:
        out["name"] = out["code"]
    for col in ["open", "high", "low", "close", "volume", "amount"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    for col in ["pe", "pb", "roe", "turnover_rate", "is_st", "delisting_risk", "negative_news"]:
        if col not in out.columns:
            out[col] = 0
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0)
    out = out.dropna(subset=["open", "high", "low", "close", "volume", "amount"])
    return out.sort_values(["code", "date"]).reset_index(drop=True)


def add_factor_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = normalize_bars(df)
    groups = out.groupby("code", group_keys=False)
    out["return_1d"] = groups["close"].pct_change().fillna(0)
    out["return_5d"] = groups["close"].pct_change(5).fillna(0)
    out["return_20d"] = groups["close"].pct_change(20).fillna(0)
    out["ma10"] = groups["close"].rolling(10).mean().reset_index(level=0, drop=True)
    out["ma20"] = groups["close"].rolling(20).mean().reset_index(level=0, drop=True)
    out["ma60"] = groups["close"].rolling(60).mean().reset_index(level=0, drop=True)
    out["volume_ma5"] = groups["volume"].rolling(5).mean().reset_index(level=0, drop=True)
    out["volume_ratio_5"] = (out["volume"] / out["volume_ma5"]).replace([math.inf, -math.inf], 0).fillna(0)
    out["high_20"] = groups["close"].rolling(20).max().reset_index(level=0, drop=True)
    out["low_20"] = groups["close"].rolling(20).min().reset_index(level=0, drop=True)
    out["drawdown_20"] = (out["close"] / out["high_20"] - 1).fillna(0)
    out["volatility_20"] = groups["return_1d"].rolling(20).std().reset_index(level=0, drop=True).fillna(0)
    return out


def latest_factor_frame(df: pd.DataFrame, as_of: str) -> pd.DataFrame:
    factors = add_factor_columns(df)
    as_of_date = pd.to_datetime(as_of).strftime("%Y-%m-%d")
    window = factors[factors["date"] <= as_of_date]
    if window.empty:
        return window
    return window.sort_values(["code", "date"]).groupby("code", as_index=False).tail(1)
