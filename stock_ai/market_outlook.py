from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from .notifier import ReliableWeChatSender
from .sentiment import SentimentResult, analyze_market_sentiment


INDEX_SYMBOLS = {
    "上证指数": "000001",
    "深证成指": "399001",
    "创业板指": "399006",
    "沪深300": "000300",
}

POSITIVE_WORDS = ("利好", "回暖", "流入", "上涨", "活跃", "宽松", "支持", "修复", "改善", "降准", "增持")
NEGATIVE_WORDS = ("利空", "下跌", "流出", "承压", "收紧", "风险", "冲突", "减持", "回落", "调整", "违约")


@dataclass(frozen=True)
class MarketDataSnapshot:
    as_of: str
    index_rows: list[dict[str, Any]]
    news_titles: list[str]
    northbound_text: str = ""
    data_notes: list[str] | None = None
    sentiment: SentimentResult | None = None


def collect_market_snapshot(as_of: str | None = None, *, db_path: Path | str | None = None) -> MarketDataSnapshot:
    report_date = as_of or date.today().strftime("%Y-%m-%d")
    notes: list[str] = []
    index_rows = _fetch_index_rows(notes)
    news_titles = _fetch_market_news(notes)
    northbound_text = _fetch_northbound_text(notes)
    sentiment = analyze_market_sentiment(news_titles, as_of=report_date)
    if db_path is not None:
        from .storage import StockDatabase

        StockDatabase(Path(db_path)).save_market_sentiment(sentiment)
    return MarketDataSnapshot(
        as_of=report_date,
        index_rows=index_rows,
        news_titles=news_titles,
        northbound_text=northbound_text,
        data_notes=notes,
        sentiment=sentiment,
    )


def build_market_outlook_message(snapshot: MarketDataSnapshot) -> str:
    score, drivers = _score_snapshot(snapshot)
    if score >= 2.0:
        view = "偏积极，明日指数有望延续修复，但需关注量能是否继续放大"
    elif score >= 0.5:
        view = "中性偏多，预计震荡上行概率略高，追高性价比一般"
    elif score <= -2.0:
        view = "偏谨慎，明日大盘可能延续震荡承压，优先控制仓位"
    elif score <= -0.5:
        view = "中性偏弱，预计分化震荡，等待资金面和主线确认"
    else:
        view = "中性震荡，方向信号不强，适合观察成交量和权重板块反馈"

    index_lines = []
    for row in snapshot.index_rows[:5]:
        name = str(row.get("name", "指数"))
        close = _float(row.get("close"))
        pct = _float(row.get("pct_chg"))
        index_lines.append(f"- {name}：{close:,.2f}，涨跌幅 {pct:+.2f}%")
    if not index_lines:
        index_lines.append("- 指数数据获取失败，本次观点降低置信度。")

    news_lines = [f"- {title}" for title in snapshot.news_titles[:6]] or ["- 新闻舆情数据获取失败，本次仅参考行情数据。"]
    driver_lines = [f"- {driver}" for driver in drivers] or ["- 未识别到强方向驱动。"]
    note_lines = [f"- {note}" for note in (snapshot.data_notes or [])]
    sentiment_lines = _format_sentiment_lines(snapshot.sentiment)

    parts = [
        f"【明日大盘预测观点】{snapshot.as_of}",
        "仅为本地量化模拟研究，不构成投资建议。",
        f"观点：{view}",
        f"综合分：{score:+.2f}",
        "",
        "今日主要指数：",
        "\n".join(index_lines),
        "",
        "市场舆论与事件线索：",
        "\n".join(news_lines),
        "",
        "A股情感分析：",
        "\n".join(sentiment_lines),
        "",
        "形成观点的关键依据：",
        "\n".join(driver_lines),
    ]
    if snapshot.northbound_text:
        parts.extend(["", f"资金线索：{snapshot.northbound_text}"])
    if note_lines:
        parts.extend(["", "数据提示：", "\n".join(note_lines)])
    parts.extend(["", "明日重点观察：成交额能否放大、权重板块是否护盘、人民币与外围市场风险偏好。"])
    return "\n".join(parts)


def send_market_outlook(snapshot: MarketDataSnapshot, *, sender: ReliableWeChatSender, output_dir: Path) -> bool:
    message = build_market_outlook_message(snapshot)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"market_outlook_{snapshot.as_of}.txt"
    path.write_text(message, encoding="utf-8")
    flushed = sender.flush_outbox()
    if flushed.failed:
        message = f"{message}\n\n发送前重试队列：成功 {flushed.sent} 条，仍失败 {flushed.failed} 条。"
    return sender.send_or_queue(message, kind="market_outlook")


def _fetch_index_rows(notes: list[str]) -> list[dict[str, Any]]:
    try:
        import akshare as ak

        spot = ak.stock_zh_index_spot_em()
        if spot is None or spot.empty:
            raise ValueError("empty index spot")
        rows = []
        for name, symbol in INDEX_SYMBOLS.items():
            matched = spot[(spot.get("代码").astype(str) == symbol) | (spot.get("名称").astype(str) == name)]
            if matched.empty:
                continue
            row = matched.iloc[0]
            rows.append(
                {
                    "name": name,
                    "close": _first_existing(row, ["最新价", "收盘", "close"]),
                    "pct_chg": _first_existing(row, ["涨跌幅", "涨跌幅%", "pct_chg"]),
                }
            )
        return rows
    except Exception as exc:
        notes.append(f"指数实时数据获取失败：{exc}")
        return _fetch_eastmoney_index_rows(notes)


def _fetch_market_news(notes: list[str]) -> list[str]:
    titles: list[str] = []
    try:
        import akshare as ak

        news = ak.stock_news_em()
        if news is None or news.empty:
            raise ValueError("empty news")
        title_col = "新闻标题" if "新闻标题" in news.columns else "标题"
        titles.extend(str(value).strip() for value in news[title_col].dropna().head(8))
    except Exception as exc:
        notes.append(f"东方财富新闻获取失败：{exc}")
    return [title for title in titles if title]


def _fetch_northbound_text(notes: list[str]) -> str:
    try:
        import akshare as ak

        getter = getattr(ak, "stock_hsgt_north_net_flow_in_em", None) or getattr(ak, "stock_hsgt_north_acc_flow_in_em", None)
        if getter is None:
            raise AttributeError("akshare has no supported northbound flow API")
        flow = getter()
        if flow is None or flow.empty:
            return ""
        row = flow.tail(1).iloc[0]
        return "，".join(f"{col} {row[col]}" for col in list(flow.columns)[:4])
    except Exception as exc:
        notes.append(f"北向资金数据获取失败：{exc}")
        return ""


def _fetch_eastmoney_index_rows(notes: list[str]) -> list[dict[str, Any]]:
    secids = "1.000001,0.399001,0.399006,1.000300"
    try:
        payload = _get_json_with_retry(
            "https://push2.eastmoney.com/api/qt/ulist.np/get",
            params={"fltt": "2", "secids": secids, "fields": "f12,f14,f2,f3"},
        )
        diff = payload.get("data", {}).get("diff", []) or []
        rows = [
            {"name": item.get("f14", item.get("f12", "指数")), "close": _float(item.get("f2")), "pct_chg": _float(item.get("f3"))}
            for item in diff
        ]
        if rows:
            notes.append("指数数据使用东方财富行情接口兜底。")
        return rows
    except Exception as exc:
        notes.append(f"东方财富指数兜底获取失败：{exc}")
        return []


def _get_json_with_retry(url: str, *, params: dict[str, str], attempts: int = 3) -> dict[str, Any]:
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            response = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            response.raise_for_status()
            return dict(response.json())
        except Exception as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return {}


def _score_snapshot(snapshot: MarketDataSnapshot) -> tuple[float, list[str]]:
    score = 0.0
    drivers: list[str] = []
    pct_values = [_float(row.get("pct_chg")) for row in snapshot.index_rows if row.get("pct_chg") is not None]
    if pct_values:
        avg_pct = sum(pct_values) / len(pct_values)
        score += avg_pct
        drivers.append(f"主要指数平均涨跌幅 {avg_pct:+.2f}%，反映收盘风险偏好。")
        positive_count = sum(1 for pct in pct_values if pct > 0)
        if positive_count >= max(2, len(pct_values) - 1):
            score += 0.7
            drivers.append("多数核心指数收涨，短线情绪有修复基础。")
        elif positive_count <= 1:
            score -= 0.7
            drivers.append("多数核心指数收跌，短线承压信号偏强。")
    if snapshot.sentiment is not None:
        sentiment_score = max(min(snapshot.sentiment.bullish_index, 1.0), -1.0)
        score += sentiment_score
        drivers.append(snapshot.sentiment.summary)
    else:
        news_text = "\n".join(snapshot.news_titles)
        pos = sum(news_text.count(word) for word in POSITIVE_WORDS)
        neg = sum(news_text.count(word) for word in NEGATIVE_WORDS)
        sentiment = min(pos - neg, 4) if pos >= neg else max(pos - neg, -4)
        score += sentiment * 0.25
        if sentiment > 0:
            drivers.append(f"新闻关键词偏积极，正向词 {pos} 个、负向词 {neg} 个。")
        elif sentiment < 0:
            drivers.append(f"新闻关键词偏谨慎，正向词 {pos} 个、负向词 {neg} 个。")
        else:
            drivers.append("新闻关键词多空接近，舆情未给出强方向。")
    if "流入" in snapshot.northbound_text or "净流入" in snapshot.northbound_text:
        score += 0.4
        drivers.append("资金线索出现流入表述，对风险偏好有支撑。")
    if "流出" in snapshot.northbound_text or "净流出" in snapshot.northbound_text:
        score -= 0.4
        drivers.append("资金线索出现流出表述，需防范权重板块承压。")
    if snapshot.data_notes:
        score -= min(len(snapshot.data_notes) * 0.2, 0.8)
        drivers.append("部分数据源获取失败，观点置信度下调。")
    return round(score, 2), drivers


def _format_sentiment_lines(sentiment: SentimentResult | None) -> list[str]:
    if sentiment is None:
        return ["- 情感分析不可用。"]
    lines = [
        f"- {sentiment.summary}",
        f"- 正向高频词：{'、'.join(sentiment.top_positive_terms) if sentiment.top_positive_terms else '无'}",
        f"- 负向高频词：{'、'.join(sentiment.top_negative_terms) if sentiment.top_negative_terms else '无'}",
    ]
    return lines


def _first_existing(row: pd.Series, columns: list[str]) -> float:
    for column in columns:
        if column in row.index:
            return _float(row[column])
    return 0.0


def _float(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0
