"""
ml_scripts/policy_mlp.py -- the actual embeddable controller: a small MLP mapping commanded
upper-rotor RPM to lower-rotor command (spacing, azimuth, rpm_lower), distilled from
the policy table in ml_scripts/policy_extract.py. This 1-input/3-output shape matches
the project's settled controller signature (2026-07-26, see README_ML.md): 1 input
(upper rotor RPM, the flight controller's demand signal), 3 outputs (azimuthal index
angle, rotor disk separation, lower rotor RPM).

Deliberately tiny (default 1 input -> 8 -> 8 -> 3 output, ReLU) -- this is meant to run
on the embedded controller commanding the rotors (an STM32 Nucleo-64 L452RE-P running
SimpleFOC, not a host PC -- see README_ML.md's hardware section), so it's kept small
enough to hand-roll a dependency-free forward pass in C rather than requiring a runtime
like ONNX Runtime / TF Lite Micro. `export_c_header()` below dumps trained weights as
static const arrays plus a matching forward-pass function.

NOTE on azimuth (RESOLVED, do not re-open): an earlier EDA (prior, 525-case, superseded
dataset) found azimuth aerodynamically negligible and this docstring used to flag that
as needing a re-check before trusting the 3-output shape below. That re-check has since
been done against the real multi-rpm_upper dataset and found the opposite: azimuth is a
real, strong, non-monotonic effect (up to an 84% total-thrust swing at fixed
spacing/RPM) -- see README_ML.md and ml_scripts/eda_azimuth_sensitivity.py. Azimuth
stays a required output; `n_outputs` should NOT be dropped from 3 to 2.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler

POLICY_OUTPUT_COLS = ["spacing_m", "azimuth_deg", "rpm_lower"]
_AZIMUTH_OUT_IDX = POLICY_OUTPUT_COLS.index("azimuth_deg")

# `[2026-07-30]`: a 2-bladed rotor's blade configuration repeats every 180 deg
# (confirmed empirically -- azimuth=+90/-90 give identical CFD results to 6
# decimal places; ml_scripts/dataset.py's azimuth_folded_deg = azimuth_deg % 180 encodes
# the same fact as a training feature). Stage-C's tiny regression net has no
# notion of that periodicity, though, and near a sharp label discontinuity
# (observed right at the low-rpm_upper edge of the trained range) it can output
# a raw azimuth outside the +/-90 deg span the surrogate was ever trained on --
# e.g. +104.6 deg, which is not physically invalid (a real actuator could do
# it), just the *same* rotor state as -75.4 deg (104.6-180) expressed the long
# way around, and one the surrogate/hardware were never actually asked about in
# that raw form. Folding back into the canonical range is not a hack, it's
# applying a physical fact the project has already confirmed.


def fold_azimuth_deg(azimuth_deg):
    """Wrap a raw azimuth output into the physically-canonical [-90, 90) range,
    using the confirmed 180-degree periodicity of a 2-bladed rotor."""
    a = np.asarray(azimuth_deg, dtype=float)
    return ((a + 90.0) % 180.0) - 90.0


@dataclass
class PolicyMLP:
    model: MLPRegressor
    x_scaler: StandardScaler
    y_scaler: StandardScaler

    def predict(self, rpm_upper) -> np.ndarray:
        x = np.atleast_2d(np.asarray(rpm_upper, dtype=float)).T
        xs = self.x_scaler.transform(x)
        ys = self.model.predict(xs)
        out = self.y_scaler.inverse_transform(ys)
        out[:, _AZIMUTH_OUT_IDX] = fold_azimuth_deg(out[:, _AZIMUTH_OUT_IDX])
        return out


def train_policy_mlp(policy_table, hidden_layer_sizes=(8, 8), seed=0) -> PolicyMLP:
    X = policy_table[["rpm_upper"]].to_numpy(dtype=float)
    Y = policy_table[POLICY_OUTPUT_COLS].to_numpy(dtype=float)

    x_scaler = StandardScaler().fit(X)
    y_scaler = StandardScaler().fit(Y)

    model = MLPRegressor(
        hidden_layer_sizes=hidden_layer_sizes,
        activation="relu",
        solver="lbfgs",   # tiny dataset (one row per rpm_upper grid point) -> lbfgs
        max_iter=5000,    # converges more reliably than adam/sgd here
        random_state=seed,
    )
    model.fit(x_scaler.transform(X), y_scaler.transform(Y))
    return PolicyMLP(model, x_scaler, y_scaler)


def _c_float(v: float) -> str:
    """
    `[2026-07-28]` PROJECT_STATE Sec 2.18: bare `f"{v:.8g}f"` drops the decimal
    point for whole numbers (e.g. 700.0 -> "700f", 0.0 -> "0f", -45.0 -> "-45f"),
    none of which are valid C floating-constants -- C requires a decimal point or
    exponent before an 'f'/'F' floating-suffix; a digit-sequence directly
    followed by 'f' is neither a valid float nor int literal and fails to
    compile. Fixed here via this helper (append ".0" before the "f" suffix when
    the formatted string has no "." or "e").
    """
    s = f"{v:.8g}"
    if not any(c in s for c in (".", "e", "E", "n", "inf")):  # "n"/"inf" catch nan/inf spellings
        s += ".0"
    return s + "f"


def export_c_header(policy: PolicyMLP, path: str, fn_name: str = "policy_forward"):
    """
    Dump weights/biases + a dependency-free forward pass as a C header, for the
    flight-controller-adjacent MCU -- an STM32 Nucleo-64 L452RE-P running SimpleFOC (see
    README_ML.md's hardware section). ReLU hidden layers, linear output, matching the
    sklearn MLPRegressor architecture trained above. Input/output are standardized in
    the same way as training (mean/scale baked in as constants), so the C caller
    passes/receives raw physical units (RPM, meters, degrees).
    """
    coefs = policy.model.coefs_
    intercepts = policy.model.intercepts_
    xm, xs = policy.x_scaler.mean_, policy.x_scaler.scale_
    ym, ys = policy.y_scaler.mean_, policy.y_scaler.scale_

    def arr(name, a):
        flat = np.asarray(a, dtype=float).flatten()
        return f"static const float {name}[{len(flat)}] = {{{', '.join(_c_float(v) for v in flat)}}};"

    lines = [
        "// Auto-generated by ml_scripts/policy_mlp.py::export_c_header -- do not edit by hand.",
        "// Regenerate after retraining. See ml_scripts/README_ML.md for the training pipeline.",
        "#pragma once",
        "",
        "#include <math.h>",
        "",
        arr("POLICY_X_MEAN", xm),
        arr("POLICY_X_SCALE", xs),
        arr("POLICY_Y_MEAN", ym),
        arr("POLICY_Y_SCALE", ys),
    ]
    layer_shapes = []
    for i, (W, b) in enumerate(zip(coefs, intercepts)):
        lines.append(arr(f"POLICY_W{i}", W.T))   # row-major, out x in
        lines.append(arr(f"POLICY_B{i}", b))
        layer_shapes.append(W.shape)  # (in, out)

    lines.append("")
    lines.append(f"// layer shapes (in, out): {layer_shapes}")
    lines.append(f"static inline void {fn_name}(float rpm_upper, float out[{len(ym)}]) {{")
    lines.append(f"    float x0 = (rpm_upper - POLICY_X_MEAN[0]) / POLICY_X_SCALE[0];")
    prev = "x0"
    prev_dim = 1
    for i, (in_dim, out_dim) in enumerate(layer_shapes):
        is_last = (i == len(layer_shapes) - 1)
        lines.append(f"    float h{i}[{out_dim}];")
        lines.append(f"    for (int o = 0; o < {out_dim}; o++) {{")
        lines.append(f"        float acc = POLICY_B{i}[o];")
        if prev_dim == 1:
            lines.append(f"        acc += POLICY_W{i}[o] * {prev};")
        else:
            lines.append(f"        for (int j = 0; j < {prev_dim}; j++) "
                          f"acc += POLICY_W{i}[o * {prev_dim} + j] * {prev}[j];")
        if is_last:
            lines.append(f"        out[o] = acc * POLICY_Y_SCALE[o] + POLICY_Y_MEAN[o];")
        else:
            lines.append(f"        h{i}[o] = acc > 0.0f ? acc : 0.0f;  // ReLU")
        lines.append("    }")
        prev, prev_dim = f"h{i}", out_dim
    lines.append(
        f"    // Fold azimuth into its physically-canonical [-90,90) range: a "
        f"2-bladed rotor's\n"
        f"    // blade pattern repeats every 180 deg (confirmed empirically, see "
        f"ml_scripts/dataset.py's\n"
        f"    // azimuth_folded_deg), so a raw output outside +/-90 deg is the "
        f"same rotor state\n"
        f"    // as (value-180), just expressed the long way around -- not a "
        f"physical error,\n"
        f"    // but outside what the surrogate/training data ever saw in raw "
        f"form.\n"
        f"    {{\n"
        f"        float m = fmodf(out[{_AZIMUTH_OUT_IDX}] + 90.0f, 180.0f);\n"
        f"        if (m < 0.0f) m += 180.0f;\n"
        f"        out[{_AZIMUTH_OUT_IDX}] = m - 90.0f;\n"
        f"    }}"
    )
    lines.append("}")

    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
