from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from .operators import OperatorEvolutionResult
from .recommendation import StockRecommendation


class StockDatabase:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def upsert_daily_bars(self, bars: pd.DataFrame) -> int:
        if bars.empty:
            return 0
        frame = bars.copy()
        if "name" not in frame.columns:
            frame["name"] = frame["code"].astype(str)
        for column in ["pe", "pb", "roe"]:
            if column not in frame.columns:
                frame[column] = 0
        rows = []
        for _, row in frame.iterrows():
            rows.append(
                (
                    str(pd.to_datetime(row["date"]).strftime("%Y-%m-%d")),
                    str(row["code"]).zfill(6),
                    _text(row.get("name")),
                    _number(row.get("open")),
                    _number(row.get("high")),
                    _number(row.get("low")),
                    _number(row.get("close")),
                    _number(row.get("volume")),
                    _number(row.get("amount")),
                    _number(row.get("pe")),
                    _number(row.get("pb")),
                    _number(row.get("roe")),
                )
            )
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO daily_bars(date, code, name, open, high, low, close, volume, amount, pe, pb, roe)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date, code) DO UPDATE SET
                    name=excluded.name,
                    open=excluded.open,
                    high=excluded.high,
                    low=excluded.low,
                    close=excluded.close,
                    volume=excluded.volume,
                    amount=excluded.amount,
                    pe=excluded.pe,
                    pb=excluded.pb,
                    roe=excluded.roe
                """,
                rows,
            )
        return len(rows)

    def load_daily_bars(self, codes: list[str], *, start_date: str, end_date: str) -> pd.DataFrame:
        selected_codes = [str(code).zfill(6) for code in codes]
        if not selected_codes:
            return pd.DataFrame()
        placeholders = ",".join("?" for _ in selected_codes)
        params: list[Any] = [start_date, end_date, *selected_codes]
        with self._connect() as conn:
            return pd.read_sql_query(
                f"""
                SELECT date, code, name, open, high, low, close, volume, amount, pe, pb, roe
                FROM daily_bars
                WHERE date BETWEEN ? AND ?
                  AND code IN ({placeholders})
                ORDER BY code, date
                """,
                conn,
                params=params,
            )

    def save_recommendation(self, *, as_of: str, recommendation: StockRecommendation) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO recommendations(as_of, code, name, score, message, created_at)
                VALUES (?, ?, ?, ?, ?, datetime('now', 'localtime'))
                ON CONFLICT(as_of) DO UPDATE SET
                    code=excluded.code,
                    name=excluded.name,
                    score=excluded.score,
                    message=excluded.message,
                    created_at=excluded.created_at
                """,
                (as_of, recommendation.code, recommendation.name, float(recommendation.score), recommendation.message),
            )

    def load_recommendations(self, limit: int = 30) -> pd.DataFrame:
        with self._connect() as conn:
            return pd.read_sql_query(
                """
                SELECT as_of, code, name, score, message, created_at
                FROM recommendations
                ORDER BY as_of DESC
                LIMIT ?
                """,
                conn,
                params=[limit],
            )

    def save_operator_evolution(self, result: OperatorEvolutionResult) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM operator_weights WHERE as_of = ?", (result.as_of,))
            conn.executemany(
                """
                INSERT INTO operator_weights(as_of, horizon, codes_json, operator, weight)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (result.as_of, result.horizon, json.dumps(result.codes, ensure_ascii=False), operator, float(weight))
                    for operator, weight in result.weights.items()
                ],
            )
            conn.execute("DELETE FROM operator_scores WHERE as_of = ?", (result.as_of,))
            conn.executemany(
                """
                INSERT INTO operator_scores(as_of, horizon, codes_json, operator, ic, top_quantile_return, hit_rate, sample_size, weight)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        result.as_of,
                        result.horizon,
                        json.dumps(result.codes, ensure_ascii=False),
                        score.name,
                        score.ic,
                        score.top_quantile_return,
                        score.hit_rate,
                        score.sample_size,
                        score.weight,
                    )
                    for score in result.scores
                ],
            )

    def load_latest_operator_weights(self) -> dict[str, float]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT operator, weight
                FROM operator_weights
                WHERE as_of = (SELECT MAX(as_of) FROM operator_weights)
                ORDER BY operator
                """
            ).fetchall()
        return {str(row["operator"]): float(row["weight"]) for row in rows}

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS daily_bars (
                    date TEXT NOT NULL,
                    code TEXT NOT NULL,
                    name TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    amount REAL NOT NULL,
                    pe REAL NOT NULL DEFAULT 0,
                    pb REAL NOT NULL DEFAULT 0,
                    roe REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY(date, code)
                );
                CREATE INDEX IF NOT EXISTS idx_daily_bars_code_date ON daily_bars(code, date);

                CREATE TABLE IF NOT EXISTS recommendations (
                    as_of TEXT PRIMARY KEY,
                    code TEXT NOT NULL,
                    name TEXT NOT NULL,
                    score REAL NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS operator_weights (
                    as_of TEXT NOT NULL,
                    horizon INTEGER NOT NULL,
                    codes_json TEXT NOT NULL,
                    operator TEXT NOT NULL,
                    weight REAL NOT NULL,
                    PRIMARY KEY(as_of, operator)
                );

                CREATE TABLE IF NOT EXISTS operator_scores (
                    as_of TEXT NOT NULL,
                    horizon INTEGER NOT NULL,
                    codes_json TEXT NOT NULL,
                    operator TEXT NOT NULL,
                    ic REAL NOT NULL,
                    top_quantile_return REAL NOT NULL,
                    hit_rate REAL NOT NULL,
                    sample_size INTEGER NOT NULL,
                    weight REAL NOT NULL,
                    PRIMARY KEY(as_of, operator)
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn


def _number(value: Any) -> float:
    try:
        if value is None or pd.isna(value):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value)
