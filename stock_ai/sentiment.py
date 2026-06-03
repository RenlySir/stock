from __future__ import annotations

import math
from dataclasses import dataclass


POSITIVE_TERMS = (
    "利好",
    "上涨",
    "走强",
    "反弹",
    "修复",
    "改善",
    "回暖",
    "流入",
    "增持",
    "放量",
    "活跃",
    "突破",
    "宽松",
    "支持",
    "降准",
    "降息",
    "盈利增长",
)

NEGATIVE_TERMS = (
    "利空",
    "下跌",
    "回落",
    "调整",
    "承压",
    "风险",
    "流出",
    "减持",
    "缩量",
    "走弱",
    "亏损",
    "违约",
    "收紧",
    "冲突",
    "监管",
    "不及预期",
)


@dataclass(frozen=True)
class SentimentResult:
    as_of: str
    positive_count: int
    negative_count: int
    neutral_count: int
    bullish_index: float
    simple_index: float
    top_positive_terms: list[str]
    top_negative_terms: list[str]
    summary: str


def analyze_market_sentiment(titles: list[str], *, as_of: str) -> SentimentResult:
    positive_count = 0
    negative_count = 0
    neutral_count = 0
    positive_hits: dict[str, int] = {}
    negative_hits: dict[str, int] = {}
    for title in titles:
        pos_score, pos_terms = _score_terms(title, POSITIVE_TERMS)
        neg_score, neg_terms = _score_terms(title, NEGATIVE_TERMS)
        for term in pos_terms:
            positive_hits[term] = positive_hits.get(term, 0) + 1
        for term in neg_terms:
            negative_hits[term] = negative_hits.get(term, 0) + 1
        if pos_score > neg_score:
            positive_count += 1
        elif neg_score > pos_score:
            negative_count += 1
        else:
            neutral_count += 1
    bullish_index = math.log((1 + positive_count) / (1 + negative_count))
    denominator = positive_count + negative_count
    simple_index = (positive_count - negative_count) / denominator if denominator else 0.0
    top_pos = _top_terms(positive_hits)
    top_neg = _top_terms(negative_hits)
    direction = "偏积极" if bullish_index > 0.2 else "偏谨慎" if bullish_index < -0.2 else "中性"
    summary = (
        f"A股舆情{direction}：正向{positive_count}条、负向{negative_count}条、"
        f"中性{neutral_count}条，BI={bullish_index:+.2f}，SI={simple_index:+.2f}"
    )
    return SentimentResult(
        as_of=as_of,
        positive_count=positive_count,
        negative_count=negative_count,
        neutral_count=neutral_count,
        bullish_index=round(bullish_index, 6),
        simple_index=round(simple_index, 6),
        top_positive_terms=top_pos,
        top_negative_terms=top_neg,
        summary=summary,
    )


def _score_terms(text: str, terms: tuple[str, ...]) -> tuple[int, list[str]]:
    hits = [term for term in terms if term in text]
    return len(hits), hits


def _top_terms(counter: dict[str, int]) -> list[str]:
    return [term for term, _ in sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:5]]
