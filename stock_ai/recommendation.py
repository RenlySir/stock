from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .operators import load_operator_weights, score_latest_with_weights
from .strategy import StrategyConfig, score_candidates, select_candidates


@dataclass(frozen=True)
class StockRecommendation:
    code: str
    name: str
    score: float
    message: str


def recommend_one_stock(
    bars: pd.DataFrame,
    codes: list[str],
    *,
    as_of: str,
    operator_weights_path: Path | str | None = None,
) -> StockRecommendation:
    universe = bars[bars["code"].astype(str).str.zfill(6).isin(codes)].copy()
    weights = load_operator_weights(operator_weights_path)
    operator_rows = score_latest_with_weights(universe, as_of=as_of, weights=weights) if weights else pd.DataFrame()
    if not operator_rows.empty and float(operator_rows.iloc[0].get("operator_score", 0)) > 0:
        base = score_candidates(universe, as_of)
        scored = operator_rows.merge(
            base[["code", "combined_score", "reasons", "risks"]],
            on="code",
            how="left",
        )
        scored["combined_score"] = scored["combined_score"].fillna(0)
        scored["final_score"] = (scored["operator_score"] * 0.65 + scored["combined_score"] * 0.35).round(2)
        row = scored.sort_values(["final_score", "operator_score", "amount"], ascending=[False, False, False]).iloc[0]
        score = float(row.get("final_score", 0))
        score_label = f"演进算子评分：{float(row.get('operator_score', 0)):.2f}，综合评分：{score:.2f}"
        operator_note = "推荐依据：历史算子演进权重 + 当日技术因子排名。\n"
    else:
        candidates = select_candidates(universe, as_of, StrategyConfig(top_n=1, min_score=0))
        if candidates.empty:
            scored = score_candidates(universe, as_of)
            if scored.empty:
                raise ValueError("no data available for recommendation")
            row = scored.iloc[0]
        else:
            row = candidates.iloc[0]
        score = float(row.get("combined_score", 0))
        score_label = f"综合评分：{score:.2f}"
        operator_note = ""
    if "row" not in locals():
        if scored.empty:
            raise ValueError("no data available for recommendation")
        row = scored.iloc[0]
    reasons = str(row.get("reasons", "")).replace(";", "、") or "综合评分最高"
    risks = str(row.get("risks", "")).replace(";", "、") or "未发现核心风险字段"
    code = str(row["code"])
    name = str(row.get("name", ""))
    message = (
        f"【每日股票推荐】\n"
        "仅为本地量化模拟研究，不构成投资建议。\n"
        f"推荐股票：{code} {name}\n"
        f"{score_label}\n"
        f"{operator_note}"
        f"推荐理由：{reasons}\n"
        f"主要风险：{risks}"
    )
    return StockRecommendation(code=code, name=name, score=score, message=message)
