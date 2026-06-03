from __future__ import annotations

import unittest

import pandas as pd

from stock_ai.rl_policy import evaluate_rl_actions


def rl_sample_bars() -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-01", periods=70)
    rows = []
    for idx, date in enumerate(dates):
        for code, base, drift in [
            ("600498", 10, 0.18),
            ("688820", 30, -0.04),
            ("300803", 20, 0.02),
        ]:
            close = base + idx * drift
            rows.append(
                {
                    "date": date.strftime("%Y-%m-%d"),
                    "code": code,
                    "name": code,
                    "open": close - 0.1,
                    "high": close + 0.2,
                    "low": close - 0.2,
                    "close": close,
                    "volume": 1_000_000 + idx * 10_000,
                    "amount": close * 1_000_000,
                    "pe": 15,
                    "pb": 2,
                    "roe": 15,
                }
            )
    return pd.DataFrame(rows)


class RlPolicyTest(unittest.TestCase):
    def test_evaluate_rl_actions_returns_continuous_action_scores(self) -> None:
        actions = evaluate_rl_actions(
            rl_sample_bars(),
            ["600498", "688820", "300803"],
            as_of="2026-04-30",
            cash=1_000_000,
        )

        self.assertEqual(actions.iloc[0]["code"], "600498")
        self.assertGreater(float(actions.iloc[0]["action"]), 0)
        self.assertLessEqual(float(actions.iloc[0]["action"]), 1)
        self.assertIn("收益-回撤", str(actions.iloc[0]["reason"]))
        self.assertIn("rl_score", actions.columns)


if __name__ == "__main__":
    unittest.main()
