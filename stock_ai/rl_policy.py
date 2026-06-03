from __future__ import annotations

import math

import pandas as pd

from .factors import add_factor_columns


def evaluate_rl_actions(
    bars: pd.DataFrame,
    codes: list[str],
    *,
    as_of: str,
    cash: float = 1_000_000,
) -> pd.DataFrame:
    """StockRL-inspired lightweight policy: state features -> continuous action [-1, 1]."""
    selected_codes = [str(code).zfill(6) for code in codes]
    frame = add_factor_columns(bars)
    frame = frame[frame["code"].astype(str).str.zfill(6).isin(selected_codes)].copy()
    frame["date"] = pd.to_datetime(frame["date"])
    as_of_date = pd.to_datetime(as_of)
    rows = []
    for code, group in frame[frame["date"] <= as_of_date].sort_values("date").groupby("code"):
        if group.empty:
            continue
        latest = group.tail(1).iloc[0]
        ret20 = _float(latest.get("return_20d"))
        ret5 = _float(latest.get("return_5d"))
        volatility = _float(latest.get("volatility_20"))
        drawdown = abs(_float(latest.get("drawdown_20")))
        volume_ratio = _float(latest.get("volume_ratio_5"))
        amount = _float(latest.get("amount"))
        liquidity = min(amount / 500_000_000, 1.0)
        reward_proxy = ret20 + 0.4 * ret5 - 0.8 * volatility - 0.5 * drawdown
        state_score = reward_proxy + 0.08 * min(volume_ratio, 3.0) + 0.05 * liquidity
        action = _squash(state_score * 4)
        rows.append(
            {
                "code": str(code).zfill(6),
                "name": str(latest.get("name", code)),
                "rl_score": round(state_score * 100, 4),
                "action": round(action, 4),
                "target_cash": round(max(action, 0) * cash * 0.2, 2),
                "reason": (
                    f"收益-回撤代理奖励{reward_proxy * 100:.2f}%，"
                    f"20日收益{ret20 * 100:.2f}%，波动{volatility * 100:.2f}%，回撤{drawdown * 100:.2f}%"
                ),
            }
        )
    if not rows:
        return pd.DataFrame(columns=["code", "name", "rl_score", "action", "target_cash", "reason"])
    return pd.DataFrame(rows).sort_values(["action", "rl_score", "code"], ascending=[False, False, True]).reset_index(drop=True)


def _squash(value: float) -> float:
    return math.tanh(value)


def _float(value: object) -> float:
    try:
        if value is None or pd.isna(value):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0
