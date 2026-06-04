from __future__ import annotations

import math
import unittest

import pandas as pd

from stock_ai.factors import add_factor_columns
from stock_ai.strategy import score_candidates


def indicator_sample_bars() -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-01", periods=90)
    rows = []
    for idx, date in enumerate(dates):
        day = date.strftime("%Y-%m-%d")
        strong_close = 10 + idx * 0.15
        weak_close = 24 - idx * 0.03
        flat_close = 16 + math.sin(idx / 3) * 0.08
        for code, name, close, volume, roe in [
            ("600498", "强趋势样本", strong_close, 1_000_000 + idx * 18_000, 16),
            ("688820", "弱趋势样本", weak_close, 900_000 - idx * 2_000, 10),
            ("300803", "震荡样本", flat_close, 800_000 + (idx % 5) * 8_000, 12),
        ]:
            rows.append(
                {
                    "date": day,
                    "code": code,
                    "name": name,
                    "open": close - 0.08,
                    "high": close + 0.22,
                    "low": close - 0.20,
                    "close": close,
                    "volume": volume,
                    "amount": close * volume,
                    "pe": 15,
                    "pb": 2,
                    "roe": roe,
                    "turnover_rate": 3,
                }
            )
    return pd.DataFrame(rows)


class StrategyIndicatorTest(unittest.TestCase):
    def test_add_factor_columns_includes_pythonstock_style_indicators(self) -> None:
        frame = add_factor_columns(indicator_sample_bars())

        for column in [
            "macd_dif",
            "macd_dea",
            "macd_hist",
            "rsi6",
            "rsi12",
            "kdj_k",
            "kdj_d",
            "kdj_j",
            "boll_mid",
            "boll_upper",
            "boll_lower",
            "boll_position",
            "cci14",
            "wr10",
            "vr24",
            "trix12",
        ]:
            self.assertIn(column, frame.columns)

        latest = frame.sort_values(["code", "date"]).groupby("code", as_index=False).tail(1)
        numeric = latest[["macd_hist", "rsi6", "kdj_j", "boll_position", "cci14", "wr10", "vr24", "trix12"]]
        self.assertFalse(numeric.isna().any().any())
        self.assertTrue(all(math.isfinite(float(value)) for value in numeric.to_numpy().ravel()))

        strong = latest[latest["code"] == "600498"].iloc[0]
        weak = latest[latest["code"] == "688820"].iloc[0]
        self.assertGreater(strong["macd_hist"], weak["macd_hist"])
        self.assertGreater(strong["trix12"], weak["trix12"])
        self.assertLess(strong["wr10"], weak["wr10"])

    def test_score_candidates_uses_technical_score_and_reports_reasons(self) -> None:
        scored = score_candidates(indicator_sample_bars(), "2026-04-30")

        self.assertIn("technical_score", scored.columns)
        strong = scored[scored["code"] == "600498"].iloc[0]
        weak = scored[scored["code"] == "688820"].iloc[0]

        self.assertGreater(strong["technical_score"], weak["technical_score"])
        self.assertGreater(strong["combined_score"], weak["combined_score"])
        self.assertIn("MACD偏强", strong["reasons"])
        self.assertIn("KDJ偏强", strong["reasons"])

    def test_score_candidates_flags_overheated_technical_risk(self) -> None:
        bars = indicator_sample_bars()
        hot_rows = []
        for idx, date in enumerate(pd.bdate_range("2026-05-01", periods=18)):
            close = 24 + idx * 0.9
            hot_rows.append(
                {
                    "date": date.strftime("%Y-%m-%d"),
                    "code": "600498",
                    "name": "强趋势样本",
                    "open": close - 0.2,
                    "high": close + 0.9,
                    "low": close - 0.1,
                    "close": close + 0.6,
                    "volume": 3_500_000 + idx * 200_000,
                    "amount": (close + 0.6) * (3_500_000 + idx * 200_000),
                    "pe": 15,
                    "pb": 2,
                    "roe": 16,
                    "turnover_rate": 3,
                }
            )
        scored = score_candidates(pd.concat([bars, pd.DataFrame(hot_rows)], ignore_index=True), "2026-05-25")

        hot = scored[scored["code"] == "600498"].iloc[0]
        self.assertIn("技术指标过热", hot["risks"])
        self.assertGreater(hot["risk_penalty"], 0)


if __name__ == "__main__":
    unittest.main()
