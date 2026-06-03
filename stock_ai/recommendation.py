from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .strategy import StrategyConfig, score_candidates, select_candidates


@dataclass(frozen=True)
class StockRecommendation:
    code: str
    name: str
    score: float
    message: str


def recommend_one_stock(bars: pd.DataFrame, codes: list[str], *, as_of: str) -> StockRecommendation:
    universe = bars[bars["code"].astype(str).str.zfill(6).isin(codes)].copy()
    candidates = select_candidates(universe, as_of, StrategyConfig(top_n=1, min_score=0))
    if candidates.empty:
        scored = score_candidates(universe, as_of)
        if scored.empty:
            raise ValueError("no data available for recommendation")
        row = scored.iloc[0]
    else:
        row = candidates.iloc[0]
    reasons = str(row.get("reasons", "")).replace(";", "、") or "综合评分最高"
    risks = str(row.get("risks", "")).replace(";", "、") or "未发现核心风险字段"
    score = float(row.get("combined_score", 0))
    code = str(row["code"])
    name = str(row.get("name", ""))
    message = (
        f"【每日股票推荐】\n"
        "仅为本地量化模拟研究，不构成投资建议。\n"
        f"推荐股票：{code} {name}\n"
        f"综合评分：{score:.2f}\n"
        f"推荐理由：{reasons}\n"
        f"主要风险：{risks}"
    )
    return StockRecommendation(code=code, name=name, score=score, message=message)
