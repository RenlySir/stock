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
    _add_pythonstock_style_indicators(out)
    return out


def latest_factor_frame(df: pd.DataFrame, as_of: str) -> pd.DataFrame:
    factors = add_factor_columns(df)
    as_of_date = pd.to_datetime(as_of).strftime("%Y-%m-%d")
    window = factors[factors["date"] <= as_of_date]
    if window.empty:
        return window
    return window.sort_values(["code", "date"]).groupby("code", as_index=False).tail(1)


def _add_pythonstock_style_indicators(out: pd.DataFrame) -> None:
    groups = out.groupby("code", group_keys=False)
    close_groups = groups["close"]
    high_groups = groups["high"]
    low_groups = groups["low"]
    volume_groups = groups["volume"]

    ema12 = close_groups.transform(lambda series: series.ewm(span=12, adjust=False).mean())
    ema26 = close_groups.transform(lambda series: series.ewm(span=26, adjust=False).mean())
    out["macd_dif"] = ema12 - ema26
    out["macd_dea"] = out.groupby("code", group_keys=False)["macd_dif"].transform(lambda series: series.ewm(span=9, adjust=False).mean())
    out["macd_hist"] = (out["macd_dif"] - out["macd_dea"]) * 2

    out["rsi6"] = _rsi(out["close"], out["code"], 6)
    out["rsi12"] = _rsi(out["close"], out["code"], 12)

    low_9 = low_groups.rolling(9, min_periods=2).min().reset_index(level=0, drop=True)
    high_9 = high_groups.rolling(9, min_periods=2).max().reset_index(level=0, drop=True)
    kdj_range = (high_9 - low_9).replace(0, math.nan)
    rsv = ((out["close"] - low_9) / kdj_range * 100).replace([math.inf, -math.inf], 50).fillna(50)
    out["kdj_k"] = rsv.groupby(out["code"], group_keys=False).transform(lambda series: series.ewm(alpha=1 / 3, adjust=False).mean())
    out["kdj_d"] = out.groupby("code", group_keys=False)["kdj_k"].transform(lambda series: series.ewm(alpha=1 / 3, adjust=False).mean())
    out["kdj_j"] = 3 * out["kdj_k"] - 2 * out["kdj_d"]

    boll_std = close_groups.rolling(20, min_periods=2).std().reset_index(level=0, drop=True)
    out["boll_mid"] = out["ma20"].fillna(out["close"])
    out["boll_upper"] = (out["boll_mid"] + 2 * boll_std).fillna(out["close"])
    out["boll_lower"] = (out["boll_mid"] - 2 * boll_std).fillna(out["close"])
    boll_width = (out["boll_upper"] - out["boll_lower"]).replace(0, math.nan)
    out["boll_position"] = ((out["close"] - out["boll_mid"]) / boll_width).replace([math.inf, -math.inf], 0).fillna(0)

    typical_price = (out["high"] + out["low"] + out["close"]) / 3
    typical_ma = typical_price.groupby(out["code"], group_keys=False).rolling(14, min_periods=3).mean().reset_index(level=0, drop=True)
    typical_deviation = (typical_price - typical_ma).abs()
    mean_deviation = typical_deviation.groupby(out["code"], group_keys=False).rolling(14, min_periods=3).mean().reset_index(level=0, drop=True)
    out["cci14"] = ((typical_price - typical_ma) / (0.015 * mean_deviation.replace(0, math.nan))).replace([math.inf, -math.inf], 0).fillna(0)

    high_10 = high_groups.rolling(10, min_periods=2).max().reset_index(level=0, drop=True)
    low_10 = low_groups.rolling(10, min_periods=2).min().reset_index(level=0, drop=True)
    wr_range = (high_10 - low_10).replace(0, math.nan)
    out["wr10"] = ((high_10 - out["close"]) / wr_range * 100).clip(lower=0, upper=100).replace([math.inf, -math.inf], 50).fillna(50)

    previous_close = close_groups.shift(1)
    up_volume = out["volume"].where(out["close"] > previous_close, 0.0)
    down_volume = out["volume"].where(out["close"] < previous_close, 0.0)
    flat_volume = out["volume"].where(out["close"] == previous_close, 0.0) * 0.5
    up_sum = (up_volume + flat_volume).groupby(out["code"], group_keys=False).rolling(24, min_periods=3).sum().reset_index(level=0, drop=True)
    down_sum = (down_volume + flat_volume).groupby(out["code"], group_keys=False).rolling(24, min_periods=3).sum().reset_index(level=0, drop=True)
    out["vr24"] = (up_sum / down_sum.where(down_sum != 0) * 100).clip(lower=0, upper=500).fillna(500)

    trix_ema1 = close_groups.transform(lambda series: series.ewm(span=12, adjust=False).mean())
    trix_ema2 = trix_ema1.groupby(out["code"], group_keys=False).transform(lambda series: series.ewm(span=12, adjust=False).mean())
    trix_ema3 = trix_ema2.groupby(out["code"], group_keys=False).transform(lambda series: series.ewm(span=12, adjust=False).mean())
    out["trix12"] = trix_ema3.groupby(out["code"], group_keys=False).pct_change().replace([math.inf, -math.inf], 0).fillna(0) * 100

    neutral_values = {
        "macd_dif": 0,
        "macd_dea": 0,
        "macd_hist": 0,
        "rsi6": 50,
        "rsi12": 50,
        "kdj_k": 50,
        "kdj_d": 50,
        "kdj_j": 50,
        "boll_position": 0,
        "cci14": 0,
        "wr10": 50,
        "vr24": 100,
        "trix12": 0,
    }
    for column, neutral in neutral_values.items():
        out[column] = pd.to_numeric(out[column], errors="coerce").replace([math.inf, -math.inf], neutral).fillna(neutral)


def _rsi(close: pd.Series, codes: pd.Series, window: int) -> pd.Series:
    delta = close.groupby(codes).diff()
    gains = delta.clip(lower=0)
    losses = (-delta.clip(upper=0)).fillna(0)
    avg_gain = gains.groupby(codes, group_keys=False).rolling(window, min_periods=window).mean().reset_index(level=0, drop=True)
    avg_loss = losses.groupby(codes, group_keys=False).rolling(window, min_periods=window).mean().reset_index(level=0, drop=True)
    denominator = (avg_gain + avg_loss).replace(0, math.nan)
    return (avg_gain / denominator * 100).replace([math.inf, -math.inf], 50).fillna(50)
