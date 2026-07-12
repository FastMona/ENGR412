# C-T Validation: Domain-Orientation Bug Investigation & Fix

**Date:** 2026-07-12
**Scope:** `scripts/run_ct_sweep.py`, `scripts/generate_propeller.py` (`full` geometry preset)

## Starting problem

A full-geometry resweep (after combining wake refinement, an LE-geometry fix, and a
retuned `firstLayerThickness`) showed mean |CT error| roughly *double* the previous
best result (650rpm: 30.0% vs. 16.6%; 1250rpm: 75.1% vs. 44.6%), plus a nonphysical
~33-37N thrust at θ=0° (should be ≈0, since a symmetric NACA 0012 blade at zero
collective and zero twist produces no net lift).

## Changes tried, in order

| # | Change | Outcome |
|---|---|---|
| 1 | Raised `refinementSurfaces`/feature-edge levels (3,4)→(5,6) | Fixed a real bug: boundary-layer prism-layer coverage went from 0% (silently reverted every iteration due to illegal faces) to 81-96% coverage. Necessary, kept. |
| 2 | Fixed degenerate zero-area STL facets at the blade leading edge (`generate_propeller.py::build_section`, dropped duplicate LE vertex) | Removed ~100 zero-area triangles per blade STL across all propeller geometries (single, coaxial, C-T). Legitimate geometry fix, kept. Did not rescue the specific LE/root/tip faces that still lack layers (accepted residual, low priority). |
| 3 | Added a `yPlus` function object to `controlDict` | Diagnostic only — revealed average y+≈228-262 (target ~100), max y+>1000 concentrated at unlayered faces. Kept for ongoing visibility. |
| 4 | Retuned `firstLayerThickness` (0.015 → 0.00657) | **Dead end.** Produced a bit-identical mesh/y+ result — `maxThicknessToMedialRatio 0.3` clamps the achievable thickness regardless of the nominal request. Reverted to 0.015. |
| 5 | Added a wake/tip-vortex volumetric refinement cylinder (`WAKE_R`/`WAKE_ZSTART`/`WAKE_ZEND`, `refinementRegions`) | Adds ~5% cells, doesn't disrupt layer coverage. Isolation-tested (disabled/re-enabled) against the θ=0° anomaly — **did not cause it** (anomaly got slightly worse without it, disproving the original wake-refinement hypothesis). Direction bug found later (#8). |
| 6 | Fixed `MRF_R` from a hardcoded 1.40 m to the derived `0.55×D_CT` (≈1.257 m), matching ART8 (Jeon & Lee 2025) Appendix A's "1.1D radial and axial" MRF-sizing convention | Thrust unaffected (<1%); torque/power shifted ~15-16% at θ=8°. Consistency fix, kept. |
| 7 | **Root-caused the θ=0° anomaly: domain z-extent was backwards.** `full` preset used 2.5D on the −z (wake/downstream) side and 10D on the +z (entrainment/upstream) side. Thrust is measured +z, so by Newton's third law the wake is pushed toward −z — the *short* boundary was sitting in the developing wake's path (causing a boundary-interaction pressure artifact), while the *long* boundary was wasted on the calm entrainment side. | **Confirmed via a symmetric-domain diagnostic**: symmetrizing the z-extent (±2.5D, same fine mesh) collapsed the θ=0° spurious thrust from a stable +37.4N plateau to <1N. Swapping `BOX_ZMIN`/`BOX_ZMAX` so the short (2.5D) leg is on +z and the long (10D) leg is on −z fixed it directly: θ=0° went from a converged wrong plateau (+37.4N) to a value still decaying toward zero (−4.4N at t=1000, trending down). This is the key fix from this session. |
| 8 | Fixed the wake/tip-vortex refinement cylinder's z-direction (`WAKE_ZEND`), which had the same backwards assumption — it extended 3D into the +z entrainment side instead of the −z wake side where tip vortices actually travel. | θ=8° (650rpm): T 180.2N→185.1N, but Q/P dropped ~11% (37.18→32.99 N·m, 2531→2246 W) and both CT and CP errors improved vs. the domain-fix-only result. No regression seen. |

## Diagnostic technique used

Three isolating background-mesh CFD runs were used to separate variables before touching
the main pipeline:
- **`full_symtest`** (temporary preset, later removed): full mesh resolution + symmetric
  ±2.5D z-domain → isolated *domain asymmetry* from *mesh resolution* as the θ=0° driver.
- **Extended `reduced`-preset θ=0° run** (t=1000→5000, resuming from a copied case):
  proved the `reduced` preset's θ=0° result was NOT the "correct ~0" it appeared to be at
  t=1000 — it was still climbing and only truly plateaus (~3.48N) around t≈1800. This
  disproved an early theory that `reduced` was simply slower to reach the same wrong
  equilibrium as `full`; it actually converges to a smaller, independent nonzero value.
- Force-time-history inspection (`postProcessing/forcesRotor/*/force.dat`) was essential
  throughout — reading only the final iteration's force is unreliable, since these MRF
  hover cases converge slowly and can plateau at a wrong equilibrium that looks
  indistinguishable from a mid-transient value without the full history.

## Post-fix validation status (both fixes applied: domain orientation + wake-zone direction)

**650rpm (Mtip=0.228), full preset, mean |CT error| = 22.4%** — better than the
regressed 30.0%, not yet back to the original best of 16.6%. θ=0° is now −0.00070
(from the equivalent of +37N pre-fix). Error is systematic, not noise: CFD overpredicts
CT at low collective (2°-7°, up to +48%) and underpredicts at high collective (8°-12°,
down to −27%), with the sign flipping around 7°-8°. A non-monotonic dip at θ=8°-9°
persists — this was flagged earlier in the investigation and is independent of the
domain-orientation bug (not resolved by this session's fixes).

**1250rpm (Mtip=0.436), full preset, mean |CT error| = 61.5%** — dominated by θ=5°
(+147%), where the experimental CT is small enough that a modest absolute overprediction
(ΔCT≈0.0031, similar in magnitude to θ=8°'s ΔCT≈0.0015) reads as a huge percentage. θ=12°
(highest-thrust, least noise-sensitive point) is only +3.9% off.

## Known open issues (not addressed this session)

1. **Non-monotonic CT dip at θ=8°-9°** (650rpm) — real, not noise; root cause unknown.
2. **CP/torque overprediction** is large and was not meaningfully improved by either fix
   (still ~+55% at θ=8° after both fixes, vs. +74% before) — a separate problem from the
   thrust/CT prediction.
3. **LE/root/tip prism-layer coverage gap** (~4-16% of blade faces still lack layers) —
   traced to a genuine curvature-vs-cell-size mismatch at a geometric singularity, not
   pursued further (diminishing returns).
4. Broader unexplored strategies: formal grid-convergence (GCI) study, compressible
   solver for the 1250rpm/Mtip=0.436 case instead of a post-hoc Prandtl-Glauert
   correction, steady MRF → transient rotating-mesh (pimpleFoam + AMI/sliding interface).

## Files changed

- `scripts/run_ct_sweep.py`: `BOX_ZMIN`/`BOX_ZMAX` (module defaults and `full` preset),
  `WAKE_ZEND`, `MRF_R`, `refinementSurfaces`/feature levels, `firstLayerThickness`
  (reverted to original), added `yPlus` function object, added wake refinement region.
- `scripts/generate_propeller.py`: `build_section()` LE duplicate-vertex fix.
