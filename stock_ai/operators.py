from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from .factors import normalize_bars


OPERATOR_COLUMNS = [
    "op_momentum_20",
    "op_macd_strength",
    "op_rsi6",
    "op_kdj_j",
    "op_boll_position",
    "op_volume_price",
    "op_breakout_20",
    "op_low_volatility",
]


@dataclass(frozen=True)
class OperatorScore:
    name: str
    ic: float
    top_quantile_return: float
    hit_rate: float
    sample_size: int
    weight: float


@dataclass(frozen=True)
class OperatorEvolutionResult:
    as_of: str
    horizon: int
    scores: list[OperatorScore]
    weights: dict[str, float]


def add_operator_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add public technical-analysis operators commonly used in A-share formula tools."""
    out = normalize_bars(df)
    groups = out.groupby("code", group_keys=False)
    close_groups = groups["close"]
    high_groups = groups["high"]
    low_groups = groups["low"]
    volume_groups = groups["volume"]

    out["return_1d"] = close_groups.pct_change().fillna(0)
    out["return_5d"] = close_groups.pct_change(5).fillna(0)
    out["return_20d"] = close_groups.pct_change(20).fillna(0)

    out["ma5"] = close_groups.rolling(5).mean().reset_index(level=0, drop=True)
    out["ma10"] = close_groups.rolling(10).mean().reset_index(level=0, drop=True)
    out["ma20"] = close_groups.rolling(20).mean().reset_index(level=0, drop=True)
    out["ma60"] = close_groups.rolling(60).mean().reset_index(level=0, drop=True)

    ema12 = close_groups.transform(lambda series: series.ewm(span=12, adjust=False).mean())
    ema26 = close_groups.transform(lambda series: series.ewm(span=26, adjust=False).mean())
    out["macd_dif"] = ema12 - ema26
    out["macd_dea"] = groups["macd_dif"].transform(lambda series: series.ewm(span=9, adjust=False).mean())
    out["macd_hist"] = (out["macd_dif"] - out["macd_dea"]) * 2

    out["rsi6"] = _rsi(out["close"], out["code"], 6)
    out["rsi12"] = _rsi(out["close"], out["code"], 12)
    out["rsi24"] = _rsi(out["close"], out["code"], 24)

    low_9 = low_groups.rolling(9).min().reset_index(level=0, drop=True)
    high_9 = high_groups.rolling(9).max().reset_index(level=0, drop=True)
    rsv = ((out["close"] - low_9) / (high_9 - low_9) * 100).replace([math.inf, -math.inf], 50).fillna(50)
    out["kdj_k"] = rsv.groupby(out["code"], group_keys=False).transform(lambda series: series.ewm(alpha=1 / 3, adjust=False).mean())
    out["kdj_d"] = out.groupby("code", group_keys=False)["kdj_k"].transform(lambda series: series.ewm(alpha=1 / 3, adjust=False).mean())
    out["kdj_j"] = 3 * out["kdj_k"] - 2 * out["kdj_d"]

    out["boll_mid"] = out["ma20"]
    boll_std = close_groups.rolling(20).std().reset_index(level=0, drop=True)
    out["boll_upper"] = out["boll_mid"] + 2 * boll_std
    out["boll_lower"] = out["boll_mid"] - 2 * boll_std

    volume_ma5 = volume_groups.rolling(5).mean().reset_index(level=0, drop=True)
    out["volume_ratio_5"] = (out["volume"] / volume_ma5).replace([math.inf, -math.inf], 0).fillna(0)
    out["high_20"] = close_groups.rolling(20).max().reset_index(level=0, drop=True)
    out["volatility_20"] = close_groups.pct_change().groupby(out["code"]).rolling(20).std().reset_index(level=0, drop=True)

    boll_width = (out["boll_upper"] - out["boll_lower"]).replace(0, pd.NA)
    out["op_momentum_20"] = out["return_20d"].fillna(0)
    out["op_macd_strength"] = (out["macd_dif"] - out["macd_dea"]).fillna(0)
    out["op_rsi6"] = out["rsi6"].fillna(50)
    out["op_kdj_j"] = out["kdj_j"].fillna(50)
    out["op_boll_position"] = ((out["close"] - out["boll_mid"]) / boll_width).replace([math.inf, -math.inf], 0).fillna(0)
    out["op_volume_price"] = (out["return_5d"] * out["volume_ratio_5"]).replace([math.inf, -math.inf], 0).fillna(0)
    out["op_breakout_20"] = (out["close"] / out["high_20"] - 1).replace([math.inf, -math.inf], 0).fillna(0)
    out["op_low_volatility"] = (-out["volatility_20"]).replace([math.inf, -math.inf], 0).fillna(0)
    return out


def evolve_operators(df: pd.DataFrame, *, as_of: str, horizon: int = 5, top_n: int = 5) -> OperatorEvolutionResult:
    if horizon <= 0:
        raise ValueError("horizon must be positive")
    frame = add_operator_columns(df)
    as_of_date = pd.to_datetime(as_of).strftime("%Y-%m-%d")
    groups = frame.groupby("code", group_keys=False)
    frame["future_return"] = groups["close"].shift(-horizon) / frame["close"] - 1
    frame["future_date"] = groups["date"].shift(-horizon)
    train = frame[(frame["date"] <= as_of_date) & (frame["future_date"] <= as_of_date)].copy()

    scores: list[OperatorScore] = []
    raw_weights: dict[str, float] = {}
    for name in OPERATOR_COLUMNS:
        valid = train[[name, "future_return"]].replace([math.inf, -math.inf], pd.NA).dropna()
        if len(valid) < 20 or valid[name].nunique() < 2:
            continue
        ic = valid[name].rank().corr(valid["future_return"].rank())
        if pd.isna(ic):
            continue
        threshold = valid[name].quantile(0.8)
        selected = valid[valid[name] >= threshold]
        if selected.empty:
            continue
        top_return = float(selected["future_return"].mean())
        hit_rate = float((selected["future_return"] > 0).mean())
        raw = max(float(ic), 0) * 0.6 + max(top_return, 0) * 3.0 + max(hit_rate - 0.5, 0) * 0.4
        raw_weights[name] = raw
        scores.append(
            OperatorScore(
                name=name,
                ic=round(float(ic), 6),
                top_quantile_return=round(top_return, 6),
                hit_rate=round(hit_rate, 6),
                sample_size=int(len(valid)),
                weight=0.0,
            )
        )

    ranked = sorted(scores, key=lambda score: (raw_weights.get(score.name, 0), score.ic, score.top_quantile_return), reverse=True)[:top_n]
    total_raw = sum(max(raw_weights.get(score.name, 0), 0) for score in ranked)
    if total_raw <= 0:
        weights = {score.name: round(1 / len(ranked), 8) for score in ranked} if ranked else {}
    else:
        weights = {score.name: round(max(raw_weights.get(score.name, 0), 0) / total_raw, 8) for score in ranked}
    if weights:
        drift = round(1.0 - sum(weights.values()), 8)
        first = next(iter(weights))
        weights[first] = round(weights[first] + drift, 8)
    ranked_with_weights = [
        OperatorScore(
            name=score.name,
            ic=score.ic,
            top_quantile_return=score.top_quantile_return,
            hit_rate=score.hit_rate,
            sample_size=score.sample_size,
            weight=weights.get(score.name, 0.0),
        )
        for score in ranked
    ]
    return OperatorEvolutionResult(as_of=as_of_date, horizon=horizon, scores=ranked_with_weights, weights=weights)


def save_operator_evolution(result: OperatorEvolutionResult, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    weights_path = output_dir / "operator_weights.json"
    scores_path = output_dir / "operator_scores.csv"
    weights_path.write_text(
        json.dumps(
            {
                "as_of": result.as_of,
                "horizon": result.horizon,
                "weights": result.weights,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    pd.DataFrame([asdict(score) for score in result.scores]).to_csv(scores_path, index=False)
    return {"weights": weights_path, "scores": scores_path}


def load_operator_weights(path: Path | str | None) -> dict[str, float]:
    if path is None:
        return {}
    weight_path = Path(path)
    if not weight_path.exists():
        return {}
    payload = json.loads(weight_path.read_text(encoding="utf-8"))
    weights = payload.get("weights", payload)
    return {str(key): float(value) for key, value in weights.items()}


def score_latest_with_weights(df: pd.DataFrame, *, as_of: str, weights: dict[str, float]) -> pd.DataFrame:
    frame = add_operator_columns(df)
    as_of_date = pd.to_datetime(as_of).strftime("%Y-%m-%d")
    latest = frame[frame["date"] <= as_of_date].sort_values(["code", "date"]).groupby("code", as_index=False).tail(1).copy()
    active = [name for name in weights if name in latest.columns]
    if latest.empty or not active:
        latest["operator_score"] = 0.0
        return latest
    latest["operator_score"] = 0.0
    for name in active:
        rank = latest[name].rank(pct=True, method="average").fillna(0)
        latest["operator_score"] += rank * weights[name] * 100
    latest["operator_score"] = latest["operator_score"].round(2)
    return latest.sort_values(["operator_score", "amount", "code"], ascending=[False, False, True])


def _rsi(close: pd.Series, codes: pd.Series, window: int) -> pd.Series:
    delta = close.groupby(codes).diff()
    gains = delta.clip(lower=0)
    losses = (-delta.clip(upper=0)).fillna(0)
    avg_gain = gains.groupby(codes).rolling(window).mean().reset_index(level=0, drop=True)
    avg_loss = losses.groupby(codes).rolling(window).mean().reset_index(level=0, drop=True)
    denominator = (avg_gain + avg_loss).replace(0, math.nan)
    return (avg_gain / denominator * 100).fillna(50).astype(float)
