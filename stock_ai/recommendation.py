from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .operators import load_operator_weights, score_latest_with_weights
from .strategy import StrategyConfig, score_candidates, select_candidates


FIXED_STOCK_METADATA = {
    "600498": {
        "name": "烽火通信",
        "industry": "通信设备",
        "concepts": "光通信、5G、6G、CPO、算力、云计算、数据中心",
    },
    "688820": {
        "name": "盛合晶微",
        "industry": "半导体",
        "concepts": "先进封装、集成电路、Chiplet、半导体封测、科创板",
    },
    "300803": {
        "name": "指南针",
        "industry": "软件开发",
        "concepts": "金融科技、互联网金融、券商概念、国产软件、人工智能",
    },
}


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
    detail_rows = universe[universe["code"].astype(str).str.zfill(6) == code].copy()
    metadata = enrich_stock_metadata(code, row, detail_rows)
    volume_summary = build_volume_summary(detail_rows, as_of=as_of)
    reason_lines = build_recommendation_reasons(row, volume_summary, reasons)
    name = metadata["name"]
    message = (
        f"【每日股票推荐】\n"
        "仅为本地量化模拟研究，不构成投资建议。\n"
        f"代码：{code}\n"
        f"名称：{name}\n"
        f"行业：{metadata['industry']}\n"
        f"概念题材：{metadata['concepts']}\n"
        f"{score_label}\n"
        f"{operator_note}"
        f"近5日交易量：{volume_summary['volume_text']}\n"
        f"近5日成交额：{volume_summary['amount_text']}\n"
        f"近5日涨跌幅：{volume_summary['return_text']}\n"
        f"推荐理由：{reason_lines}\n"
        f"主要风险：{risks}"
    )
    return StockRecommendation(code=code, name=name, score=score, message=message)


def enrich_stock_metadata(code: str, row: pd.Series, bars: pd.DataFrame) -> dict[str, str]:
    name = _clean_text(row.get("name")) or code
    industry = _clean_text(row.get("industry")) or _clean_text(row.get("行业"))
    concepts = _clean_text(row.get("concepts")) or _clean_text(row.get("概念题材")) or _clean_text(row.get("concept"))
    if (not industry or not concepts or name == code) and not bars.empty:
        latest = bars.sort_values("date").tail(1).iloc[0]
        name = _clean_text(latest.get("name")) or name
        industry = industry or _clean_text(latest.get("industry")) or _clean_text(latest.get("行业"))
        concepts = concepts or _clean_text(latest.get("concepts")) or _clean_text(latest.get("概念题材")) or _clean_text(latest.get("concept"))
    fetched = _fetch_stock_metadata(code) if (not industry or not concepts or name == code) else {}
    fallback = FIXED_STOCK_METADATA.get(code, {})
    final_name = fetched.get("name") or name or fallback.get("name", code)
    if final_name == code and fallback.get("name"):
        final_name = fallback["name"]
    return {
        "name": final_name,
        "industry": fetched.get("industry") or industry or fallback.get("industry", "数据源未提供"),
        "concepts": _format_concepts(fetched.get("concepts") or concepts or fallback.get("concepts", "数据源未提供")),
    }


def build_volume_summary(bars: pd.DataFrame, *, as_of: str) -> dict[str, str]:
    if bars.empty:
        return {"volume_text": "数据源未提供", "amount_text": "数据源未提供", "return_text": "数据源未提供", "volume_ratio": 0.0}
    frame = bars.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    as_of_date = pd.to_datetime(as_of)
    frame = frame[frame["date"] <= as_of_date].sort_values("date")
    recent = frame.tail(5)
    if recent.empty:
        return {"volume_text": "数据源未提供", "amount_text": "数据源未提供", "return_text": "数据源未提供", "volume_ratio": 0.0}
    volume = pd.to_numeric(recent["volume"], errors="coerce").fillna(0)
    amount = pd.to_numeric(recent["amount"], errors="coerce").fillna(0)
    close = pd.to_numeric(recent["close"], errors="coerce").dropna()
    previous = frame.iloc[:-5].tail(5)
    previous_volume = pd.to_numeric(previous["volume"], errors="coerce").fillna(0).mean() if not previous.empty else 0
    recent_volume = float(volume.mean())
    volume_ratio = recent_volume / previous_volume if previous_volume else 0.0
    return_pct = (float(close.iloc[-1]) / float(close.iloc[0]) - 1) * 100 if len(close) >= 2 and float(close.iloc[0]) else 0.0
    return {
        "volume_text": f"日均 {_human_number(recent_volume)}，较前5日 {volume_ratio:.2f} 倍" if volume_ratio else f"日均 {_human_number(recent_volume)}",
        "amount_text": f"日均 {_human_money(float(amount.mean()))}",
        "return_text": f"{return_pct:+.2f}%",
        "volume_ratio": volume_ratio,
    }


def build_recommendation_reasons(row: pd.Series, volume_summary: dict[str, Any], base_reasons: str) -> str:
    reasons = [item for item in str(base_reasons).split("、") if item]
    operator_score = _safe_float(row.get("operator_score"))
    if operator_score > 0:
        reasons.insert(0, f"演进算子评分 {operator_score:.2f}")
    volume_ratio = _safe_float(volume_summary.get("volume_ratio"))
    if volume_ratio >= 1.2:
        reasons.append(f"近5日日均量较前5日放大至 {volume_ratio:.2f} 倍")
    elif volume_ratio > 0:
        reasons.append(f"近5日日均量为前5日 {volume_ratio:.2f} 倍，量能相对平稳")
    return "、".join(dict.fromkeys(reasons)) or "固定股票池中综合评分最高"


def _fetch_stock_metadata(code: str) -> dict[str, str]:
    data: dict[str, str] = {}
    try:
        import akshare as ak

        individual = ak.stock_individual_info_em(symbol=code)
        if individual is not None and not individual.empty:
            for _, item in individual.iterrows():
                key = str(item.iloc[0])
                value = _clean_text(item.iloc[1])
                if key in {"股票简称", "简称"} and value:
                    data["name"] = value
                if key in {"行业", "所属行业"} and value:
                    data["industry"] = value
    except Exception:
        pass
    return data


def _format_concepts(value: str) -> str:
    parts = [part.strip() for part in str(value).replace(";", "、").replace(",", "、").split("、") if part.strip()]
    return "、".join(parts[:6]) if parts else "数据源未提供"


def _clean_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text in {"", "nan", "None"} else text


def _human_number(value: float) -> str:
    if value >= 100_000_000:
        return f"{value / 100_000_000:.2f}亿股"
    if value >= 10_000:
        return f"{value / 10_000:.2f}万股"
    return f"{value:.0f}股"


def _human_money(value: float) -> str:
    if value >= 100_000_000:
        return f"{value / 100_000_000:.2f}亿元"
    if value >= 10_000:
        return f"{value / 10_000:.2f}万元"
    return f"{value:.0f}元"


def _safe_float(value: Any) -> float:
    try:
        if value is None or pd.isna(value):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0
