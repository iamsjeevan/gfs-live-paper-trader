"""Position sizing logic: volatility targeting, leverage capping, and direction modes."""

from typing import Optional
import numpy as np
import pandas as pd


def compute_target_weights(
    df: pd.DataFrame,
    score_col: str = "momentum_score",
    vol_col: str = "realized_vol",
    target_vol: float = 0.40,
    max_leverage: float = 1.0,
    sizing_mode: str = "vol_targeted",
    direction_mode: str = "long_short",
    min_weight: float = 0.0,
) -> pd.DataFrame:
    """Calculate target portfolio weights based on momentum score and volatility.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame containing score_col and vol_col.
    score_col : str
        Column name for momentum score (values in {-4, -2, 0, 2, 4}).
    vol_col : str
        Column name for realized volatility.
    target_vol : float
        Target annualized volatility (risk budget, e.g. 0.40 for 40%).
    max_leverage : float
        Maximum gross leverage cap (e.g. 1.0, 2.0, 3.0, 5.0).
    sizing_mode : str
        'vol_targeted': (score / 4.0) * (target_vol / realized_vol), capped at max_leverage.
        'unscaled': (score / 4.0) * max_leverage.
        'binary_unscaled': np.sign(score) * max_leverage.
        'buy_and_hold': constant 1.0 weight (or max_leverage).
    direction_mode : str
        'long_short': full range [-max_leverage, +max_leverage].
        'long_only': non-negative [0.0, +max_leverage], negative weights become 0.0 (cash).
    min_weight : float
        Minimum absolute weight below which position is zeroed (deadband/threshold).

    Returns
    -------
    pd.DataFrame
        DataFrame with added column 'target_weight'.
    """
    out = df.copy()
    scores = out[score_col].fillna(0.0)

    if sizing_mode == "buy_and_hold":
        raw_weight = pd.Series(max_leverage, index=out.index)
    elif sizing_mode == "unscaled":
        raw_weight = (scores / 4.0) * max_leverage
    elif sizing_mode == "binary_unscaled":
        raw_weight = np.sign(scores) * max_leverage
    elif sizing_mode == "vol_targeted":
        vol = out[vol_col].replace(0.0, np.nan).ffill().fillna(0.40)
        # Position size proportional to score * (risk_budget / volatility)
        raw_weight = (scores / 4.0) * (target_vol / vol)
    else:
        raise ValueError(f"Unknown sizing_mode '{sizing_mode}'.")

    # Apply leverage cap
    capped_weight = raw_weight.clip(lower=-max_leverage, upper=max_leverage)

    # Direction mode filtering
    if direction_mode == "long_only":
        final_weight = capped_weight.clip(lower=0.0)
    elif direction_mode == "long_short":
        final_weight = capped_weight
    else:
        raise ValueError(f"Unknown direction_mode '{direction_mode}'.")

    # Optional deadband threshold
    if min_weight > 0:
        final_weight = np.where(np.abs(final_weight) < min_weight, 0.0, final_weight)

    # Where score was NaN (warmup period), target_weight is 0.0
    nan_mask = out[score_col].isna()
    final_weight = pd.Series(final_weight, index=out.index)
    final_weight[nan_mask] = 0.0

    out["target_weight"] = final_weight
    return out
