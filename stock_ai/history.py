from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import requests

from .realtime import market_symbol


def load_or_fetch_histories(codes: list[str], *, start_date: str, end_date: str, cache_dir: Path) -> pd.DataFrame:
    cache_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    errors: list[str] = []
    for code in codes:
        path = cache_dir / f"hist_{code}_{start_date}_{end_date}.csv"
        try:
            if path.exists():
                frames.append(pd.read_csv(path, dtype={"code": str}))
                continue
            frame = fetch_sina_daily(code, start_date=start_date, end_date=end_date)
            frame.to_csv(path, index=False)
            frames.append(frame)
        except Exception as exc:
            errors.append(f"{code}: {exc}")
            continue
    if not frames:
        if errors:
            raise ValueError("no historical rows fetched; " + "; ".join(errors))
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    if errors:
        out.attrs["fetch_errors"] = errors
    return out


def fetch_sina_daily(code: str, *, start_date: str, end_date: str) -> pd.DataFrame:
    ak_frame = _fetch_akshare_daily(code, start_date=start_date, end_date=end_date)
    if not ak_frame.empty:
        return ak_frame
    url = "https://finance.sina.com.cn/realstock/company/{}/hisdata/klc_kl.js".format(market_symbol(code))
    try:
        response = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        text = response.text
    except Exception as exc:
        eastmoney_frame = _fetch_eastmoney_daily(code, start_date=start_date, end_date=end_date)
        if not eastmoney_frame.empty:
            return eastmoney_frame
        raise ValueError(f"no historical rows fetched for {code}; sina error: {exc}") from exc
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
        eastmoney_frame = _fetch_eastmoney_daily(code, start_date=start_date, end_date=end_date)
        if not eastmoney_frame.empty:
            return eastmoney_frame
        raise ValueError(f"no historical rows fetched for {code}")
    return out.sort_values("date")


def _fetch_eastmoney_daily(code: str, *, start_date: str, end_date: str) -> pd.DataFrame:
    secid = _eastmoney_secid(code)
    response = requests.get(
        "https://push2his.eastmoney.com/api/qt/stock/kline/get",
        params={
            "secid": secid,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101",
            "fqt": "0",
            "beg": start_date.replace("-", ""),
            "end": end_date.replace("-", ""),
        },
        timeout=10,
        headers={"Referer": "https://quote.eastmoney.com/", "User-Agent": "Mozilla/5.0"},
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or int(payload.get("rc", -1)) != 0:
        return pd.DataFrame()
    data = payload.get("data")
    if not isinstance(data, dict):
        return pd.DataFrame()
    klines = data.get("klines", [])
    if not isinstance(klines, list):
        return pd.DataFrame()
    rows = []
    name = str(data.get("name") or code)
    for item in klines:
        parts = str(item).split(",")
        if len(parts) < 7:
            continue
        day = parts[0]
        if not (start_date <= day <= end_date):
            continue
        rows.append(
            {
                "date": day,
                "code": str(code).zfill(6),
                "name": name,
                "open": _num(parts[1]),
                "close": _num(parts[2]),
                "high": _num(parts[3]),
                "low": _num(parts[4]),
                "volume": _num(parts[5]) * 100,
                "amount": _num(parts[6]),
                "pe": 0,
                "pb": 0,
                "roe": 0,
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.dropna(subset=["open", "high", "low", "close"]).sort_values("date")


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


def _eastmoney_secid(code: str) -> str:
    code = str(code).zfill(6)
    market = "1" if code.startswith(("5", "6", "9")) else "0"
    return f"{market}.{code}"


def _num(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
