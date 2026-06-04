from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .factors import latest_factor_frame


@dataclass(frozen=True)
class StrategyConfig:
    top_n: int = 3
    min_score: float = 45.0


def score_candidates(df: pd.DataFrame, as_of: str) -> pd.DataFrame:
    rows = latest_factor_frame(df, as_of)
    if rows.empty:
        return rows
    scored = rows.copy()
    fundamental = (
        ((scored["pe"] > 0) & (scored["pe"] <= 20)).astype(float) * 18
        + ((scored["pb"] > 0) & (scored["pb"] <= 5)).astype(float) * 10
        + (scored["roe"].clip(lower=0, upper=25) / 25 * 18)
    )
    momentum = (
        scored["return_20d"].clip(lower=-0.2, upper=0.5) / 0.5 * 24
        + scored["return_5d"].clip(lower=-0.1, upper=0.2) / 0.2 * 8
        + (scored["close"] > scored["ma20"]).astype(float) * 8
        + (scored["close"] > scored["ma60"]).astype(float) * 6
    )
    liquidity = (scored["amount"].clip(lower=0, upper=500_000_000) / 500_000_000 * 8)
    volume = scored["volume_ratio_5"].clip(lower=0, upper=3) / 3 * 6
    technical = (
        (scored["macd_hist"] > 0).astype(float) * 3
        + (scored["macd_dif"] > scored["macd_dea"]).astype(float) * 3
        + ((scored["rsi6"] >= 50) & (scored["rsi6"] <= 82)).astype(float) * 3
        + ((scored["kdj_j"] >= 50) & (scored["kdj_j"] <= 105)).astype(float) * 3
        + ((scored["boll_position"] >= -0.1) & (scored["boll_position"] <= 0.75)).astype(float) * 2
        + ((scored["cci14"] >= 0) & (scored["cci14"] <= 180)).astype(float) * 3
        + ((scored["wr10"] >= 8) & (scored["wr10"] <= 45)).astype(float) * 2
        + ((scored["vr24"] >= 110) & (scored["vr24"] <= 420)).astype(float) * 2
        + (scored["trix12"] > 0).astype(float) * 2
    )
    technical_overheat_penalty = (
        (scored["rsi6"] >= 86).astype(float) * 3
        + (scored["kdj_j"] >= 110).astype(float) * 3
        + (scored["cci14"] >= 220).astype(float) * 3
        + (scored["wr10"] <= 5).astype(float) * 2
        + (scored["boll_position"] >= 0.9).astype(float) * 2
        + (scored["vr24"] >= 460).astype(float) * 2
    )
    risk_penalty = (
        (scored["drawdown_20"].abs().clip(lower=0, upper=0.25) / 0.25 * 10)
        + (scored["volatility_20"].clip(lower=0, upper=0.08) / 0.08 * 8)
        + technical_overheat_penalty
        + (scored["is_st"] > 0).astype(float) * 50
        + (scored["delisting_risk"] > 0).astype(float) * 50
        + (scored["negative_news"] > 0).astype(float) * 15
    )
    scored["fundamental_score"] = fundamental.round(2)
    scored["momentum_score"] = momentum.round(2)
    scored["liquidity_score"] = liquidity.round(2)
    scored["volume_score"] = volume.round(2)
    scored["technical_score"] = technical.round(2)
    scored["technical_overheat_penalty"] = technical_overheat_penalty.round(2)
    scored["risk_penalty"] = risk_penalty.round(2)
    scored["combined_score"] = (fundamental + momentum + liquidity + volume + technical - risk_penalty).clip(lower=0).round(2)
    scored["reasons"] = scored.apply(_reasons, axis=1)
    scored["risks"] = scored.apply(_risks, axis=1)
    return scored.sort_values(["combined_score", "amount", "code"], ascending=[False, False, True])


def select_candidates(df: pd.DataFrame, as_of: str, config: StrategyConfig) -> pd.DataFrame:
    scored = score_candidates(df, as_of)
    if scored.empty:
        return scored
    filtered = scored[scored["combined_score"] >= config.min_score].copy()
    return filtered.head(config.top_n)


def _reasons(row: pd.Series) -> str:
    reasons = []
    if row["pe"] > 0 and row["pe"] <= 20:
        reasons.append("PE<=20")
    if row["roe"] >= 15:
        reasons.append("ROE>=15")
    if row["return_20d"] > 0:
        reasons.append("20日动量为正")
    if row["close"] > row["ma20"]:
        reasons.append("站上MA20")
    if row["volume_ratio_5"] >= 1.5:
        reasons.append("相对5日均量放量")
    if row.get("macd_hist", 0) > 0 and row.get("macd_dif", 0) > row.get("macd_dea", 0):
        reasons.append("MACD偏强")
    if row.get("kdj_j", 50) >= 50 and row.get("kdj_j", 50) <= 105:
        reasons.append("KDJ偏强")
    if row.get("trix12", 0) > 0:
        reasons.append("TRIX趋势向上")
    if row.get("vr24", 100) >= 110:
        reasons.append("VR量能确认")
    return ";".join(reasons)


def _risks(row: pd.Series) -> str:
    risks = []
    if row["drawdown_20"] <= -0.12:
        risks.append("20日回撤较大")
    if row["volatility_20"] >= 0.04:
        risks.append("波动偏高")
    if row["pe"] <= 0 or row["roe"] <= 0:
        risks.append("基本面字段缺失或异常")
    if row.get("technical_overheat_penalty", 0) > 0:
        risks.append("技术指标过热")
    if row["is_st"] > 0 or row["delisting_risk"] > 0:
        risks.append("ST或退市风险")
    return ";".join(risks)
