from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import requests

from .realtime import market_symbol


def load_or_fetch_histories(codes: list[str], *, start_date: str, end_date: str, cache_dir: Path) -> pd.DataFrame:
    cache_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for code in codes:
        path = cache_dir / f"hist_{code}_{start_date}_{end_date}.csv"
        if path.exists():
            frames.append(pd.read_csv(path, dtype={"code": str}))
            continue
        frame = fetch_sina_daily(code, start_date=start_date, end_date=end_date)
        frame.to_csv(path, index=False)
        frames.append(frame)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def fetch_sina_daily(code: str, *, start_date: str, end_date: str) -> pd.DataFrame:
    ak_frame = _fetch_akshare_daily(code, start_date=start_date, end_date=end_date)
    if not ak_frame.empty:
        return ak_frame
    url = "https://finance.sina.com.cn/realstock/company/{}/hisdata/klc_kl.js".format(market_symbol(code))
    response = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    text = response.text
    # Fallback: use a small synthetic-like empty frame when Sina historical endpoint format changes.
    # The real-time monitor remains live through hq.sinajs.cn.
    rows = []
    for item in text.split(";"):
        if not item or "," not in item:
            continue
        parts = item.replace("\\n", "").replace('"', "").split(",")
        if len(parts) < 6 or not parts[0][:4].isdigit():
            continue
        day = parts[0][:10]
        if not (start_date <= day <= end_date):
            continue
        rows.append(
            {
                "date": day,
                "code": code,
                "name": code,
                "open": _num(parts[1]),
                "high": _num(parts[2]),
                "low": _num(parts[3]),
                "close": _num(parts[4]),
                "volume": _num(parts[5]) * 100,
                "amount": _num(parts[4]) * _num(parts[5]) * 100,
                "pe": 0,
                "pb": 0,
                "roe": 0,
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        raise ValueError(f"no historical rows fetched for {code}")
    return out.sort_values("date")


def _fetch_akshare_daily(code: str, *, start_date: str, end_date: str) -> pd.DataFrame:
    try:
        import akshare as ak

        df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
            adjust="",
            timeout=10,
        )
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df["日期"]).dt.strftime("%Y-%m-%d"),
            "code": code,
            "name": code,
            "open": pd.to_numeric(df["开盘"], errors="coerce"),
            "high": pd.to_numeric(df["最高"], errors="coerce"),
            "low": pd.to_numeric(df["最低"], errors="coerce"),
            "close": pd.to_numeric(df["收盘"], errors="coerce"),
            "volume": pd.to_numeric(df["成交量"], errors="coerce") * 100,
            "amount": pd.to_numeric(df["成交额"], errors="coerce"),
            "pe": 0,
            "pb": 0,
            "roe": 0,
        }
    )
    return out.dropna(subset=["open", "high", "low", "close"]).sort_values("date")


def default_history_end() -> str:
    return date.today().strftime("%Y-%m-%d")


def _num(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
