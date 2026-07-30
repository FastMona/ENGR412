"""
ml/surrogate.py -- Phase 1 offline forward surrogate (per project plan: "Phase 1
targets an offline-trained MLP surrogate").

Learns performance (thrust_total_N, power_total_W, fom_total) as a function of the
full design vector (rpm_upper, spacing_m, azimuth_deg, rpm_lower). This is the
*forward* model -- it does not by itself answer "what lower-rotor settings should I
command for a given upper RPM", it only predicts performance for a given full
combination. ml/policy_extract.py uses this surrogate to answer that question by
grid-searching it, then distills the result into ml/policy_mlp.py, the actual
embeddable controller.

Uses scikit-learn's MLPRegressor rather than a deep-learning framework: the dataset
is O(100-1000) rows (a handful of CFD sweeps, not big data), and sklearn keeps the
dependency footprint light while still exposing raw weight matrices (coefs_/
intercepts_) needed for the embedded C export in policy_mlp.py.
"""
from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler

from ml.dataset import FEATURE_COLS_FULL, TARGET_COLS


@dataclass
class Surrogate:
    model: MLPRegressor
    x_scaler: StandardScaler
    y_scaler: StandardScaler
    feature_cols: list
    target_cols: list

    def predict(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        Xv = X[self.feature_cols].to_numpy() if isinstance(X, pd.DataFrame) else np.asarray(X)
        Xs = self.x_scaler.transform(Xv)
        Ys = self.model.predict(Xs)
        return self.y_scaler.inverse_transform(Ys)


def train_surrogate(
    df: pd.DataFrame,
    feature_cols: list = None,
    target_cols: list = None,
    hidden_layer_sizes=(32, 32),
    max_iter=2000,
    seed=0,
) -> Surrogate:
    feature_cols = feature_cols or FEATURE_COLS_FULL
    target_cols  = target_cols or TARGET_COLS

    X = df[feature_cols].to_numpy(dtype=float)
    Y = df[target_cols].to_numpy(dtype=float)

    x_scaler = StandardScaler().fit(X)
    y_scaler = StandardScaler().fit(Y)

    model = MLPRegressor(
        hidden_layer_sizes=hidden_layer_sizes,
        activation="relu",
        solver="adam",
        max_iter=max_iter,
        random_state=seed,
        early_stopping=True,
        n_iter_no_change=25,
        validation_fraction=0.15,
    )
    model.fit(x_scaler.transform(X), y_scaler.transform(Y))

    return Surrogate(model, x_scaler, y_scaler, feature_cols, target_cols)


def evaluate(surrogate: Surrogate, df_val: pd.DataFrame) -> dict:
    """Simple held-out R^2 / mean-abs-percentage-error per target, for sanity-checking
    against real CFD data once it exists. Not a substitute for physically inspecting
    predictions the way analyze_sweep.py / C-T_validation.py do for the CFD side."""
    pred = surrogate.predict(df_val)
    true = df_val[surrogate.target_cols].to_numpy(dtype=float)
    out = {}
    for i, col in enumerate(surrogate.target_cols):
        yt, yp = true[:, i], pred[:, i]
        ss_res = np.sum((yt - yp) ** 2)
        ss_tot = np.sum((yt - yt.mean()) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
        mape = np.mean(np.abs((yt - yp) / np.where(yt == 0, np.nan, yt))) * 100
        out[col] = {"r2": r2, "mape_pct": mape}
    return out
