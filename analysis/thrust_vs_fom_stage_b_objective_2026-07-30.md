# Stage-B objective: thrust_total vs. figure of merit `[2026-07-30]`

Resolves the discussion opened by PS item 4.9 (raised against §2.10, 2026-07-26):
whether maximizing `thrust_total` subject to a power constraint is the right
stage-B objective, given the risk of a degenerate solution (e.g. pinning
`rpm_lower` to the boundary of its swept range rather than a genuine interior
optimum, if the power constraint doesn't bind tightly there).

## Literature check

Six papers in the project knowledge base were checked for how they define a
coaxial/stacked-rotor optimization or evaluation objective. None use raw
thrust maximization under a power cap:

- **Qin & Yang (2025)**, X2TD coaxial rotor blade optimization: objective is
  `Maximize FM = (CTu+CTl)^1.5 / (sqrt(2)*(|CQu|+|CQl|))`, holding total CT
  constant via trim — not power-constrained thrust.
- **Jeon & Lee (2025)**, co-axial co-rotating propeller parameter study:
  reports thrust, torque, *and* FoM, treats FoM as the efficiency metric of
  record across the offset/index-angle/RPM-differential sweep.
- **Jacobellis et al. (2021)** and **Hong et al. (2023)**, stacked-rotor
  hover papers: use "power loading" (C_T/C_P, dimensionally T·Vtip/P) — the
  same trade-off as FoM, just non-dimensionalized differently.
- **Leishman & Syal (2008)**, already cited in the report (footnote e2):
  established the standard coaxial-rotor FoM expression this project's own
  `figure_of_merit()` (`cfd_scripts/run_sweep.py`) already implements.
- Broader search adds two more members of the same family: thrust-to-power
  ratio (dimensional cousin of FoM) and Pareto/multi-objective formulations
  (e.g. NSGA-II treating thrust and efficiency as separate objectives) —
  a distinct third option, not pursued here.

Conclusion at this stage: FoM (or an equivalent power-loading metric) is the
literature-supported choice, not power-constrained thrust_total. This part of
4.9's question — *is FoM a legitimate alternative* — is answered yes.

## Pipeline validation: is `fom_total` trustworthy enough to act on?

A literature-support argument is only useful if this project's own
`fom_total` is numerically trustworthy. Two validation cases were built to
check this, both added to `cfd_scripts/`:

### `run_x2td_validation.py` / `X2TD_validation.py`

Validates against Qin & Yang (2025) baseline-2 (X2TD blade, pre-optimization):
FM=0.4102 at CT=0.005, Mtip=0.563, H/D=0.0568. The real X2TD blade blends
three proprietary Sikorsky airfoils by radial station (DBLN-526 root /
SC1012R8 mid-span / SSCA09 tip; Passe et al., 2015) — not reproducible with
`generate_propeller.py`'s NACA-4-digit-only support. Of the three, only
SC1012R8 (the load-carrying mid-span section) was judged worth approximating:
DBLN-526 exists to suppress reverse flow on the retreating blade in forward
flight (this project is hover-only, so irrelevant), and SSCA09 is a transonic
section tested to M=1.07 (this project's entire design space tops out around
Mtip~0.44 in the C-T validation cases and ~0.18 in production — nowhere near
transonic, so irrelevant). SC1012R8's actual measured geometry (airfoiltools.com
/ UIUC coords: 12.0% t/c at 27.8% chord, 2.7% camber at 21.8% chord) is best
matched by **NACA 2412**, not this project's default NACA4412 (4% camber at
40% chord — a poorer match on both camber magnitude and position).

Three failed/corrected attempts before a usable result, each worth keeping on
record:

1. **Chord derived from X2TD's stated aspect ratio (19.2) as R/c_mean, giving
   c≈0.026m.** Failed completely: `constant/polyMesh/boundary` came back with
   only `inlet`/`outlet`/`sides` — `upperBlade`/`lowerBlade` never made it
   into the mesh at all. `TEMPLATE_DUAL`'s existing `snappyHexMeshDict`
   (tuned for this project's default ~0.08m root-chord blade) couldn't
   resolve a blade this thin; it vanished during castellation rather than
   under-resolving gracefully. Every case returned exactly 0 thrust/torque
   and was **wrongly flagged `CONVERGED_TIGHT`** — a real blind spot in
   `run_sweep.py`'s `_tail_ratio()`: an identically-zero force history
   short-circuits `mean_abs < 1e-6` to ratio=0.0, reading as "perfectly
   converged" rather than being flagged as suspicious. Worth a separate fix.
2. **Chord bumped to 0.08m** (this project's own known-meshable scale) at the
   literal H/D=0.0568 (spacing=0.0568m). Fixed the meshing, but
   `thrust_upper_N` came back **negative in 5 of 7 collective cases** while
   `thrust_lower_N` stayed a healthy +15N throughout; FM was non-monotonic;
   the 0° case never converged (hit the 1500-iteration cap, `BORDERLINE`).
   Diagnosis: at spacing=0.0568m, `write_case_configs_dual`'s own MRF-zone
   formula gives `mrf_dz`=±0.0184m — and an 8cm-chord blade's own z-extent
   (thickness + collective-tilt projection of the chord line, ~2.1cm at 12°)
   is in the same ballpark as that zone half-height. Part of the blade was
   very likely sitting outside its own assigned MRF rotating zone, treated
   as stationary geometry inside a nominally-rotating frame.
3. **Spacing relaxed to 0.10m** (H/D=0.10, abandoning Qin & Yang's exact
   H/D=0.0568) — chosen specifically because it matches this project's own
   `co_rot_meshcheck` point, giving `mrf_dz`=±0.04m, ~2x the blade's z-extent.
   This produced a clean result: `thrust_upper_N` positive across all 7
   cases, all `CONVERGED`/`CONVERGED_TIGHT`, no iteration-cap hits. One
   smaller pattern remained — `thrust_lower_N` slightly negative at low
   collective (0-4°: -0.21N, -1.60N, -1.35N), consistent with the lower rotor
   sitting in the upper rotor's downwash (the same interference mechanism
   §2.10's momentum-theory discussion already describes) pushing its local
   AoA below the airfoil's zero-lift angle at low commanded pitch. Judged
   **not production-relevant**: production runs a fixed, calculated
   collective for a tapered/twisted blade, not a swept flat collective
   through the near-zero-thrust region. Above that region, FM climbs cleanly
   with CT (6°: 0.3698, 8°: 0.4033, 10°: 0.4241, 12°: 0.4820).

Final numeric result: **interpolated FM at CT=0.005 = 0.1672 (40.8% of Qin &
Yang's 0.4102)**. This should not be read as "the pipeline underperforms the
literature by 60%" — CT=0.005 falls between the 2° and 4° points, i.e. inside
the low-collective interference region just discussed, the least-trustworthy
part of the sweep. The trend above that region (6-12°) looks physically sane.

Documented deviations from Qin & Yang's exact operating point, in total:
airfoil (NACA2412 single section vs. the real 3-airfoil blend), tip Mach
(0.137 vs. 0.563 — matching RPM instead of Mach keeps the case inside this
project's already-characterized ~3% incompressible-solver bias regime from
the C-T validation, rather than extrapolating into an uncharacterized one),
chord (0.08m, chosen for meshability not literature fidelity), and spacing
(H/D=0.10 vs. 0.0568). This is a trend/plausibility check on the airfoil
approximation, not a wind-tunnel-grade replication.

### `run_x2td_meshcheck.py`

Re-runs the two "healthy" X2TD validation points (8°, 12°) on
`TEMPLATE_DUAL_MESHCHECK` — the same refined mesh `co_rot_meshcheck` already
uses at D=1.0m/spacing=0.10m — to check whether `co_rot_meshcheck`'s own
finding (`fom_total` moves 20-99% under refinement) is specific to the
default NACA4412 blade or a more general property of this spacing.

Result: **`fom_total` moved -8.6% at 8° and -26.8% at 12°**, both in the
same direction (refined mesh gives lower FoM than coarse in both cases — the
coarse mesh production would actually see is systematically optimistic here,
not just noisy). This generalizes the `co_rot_meshcheck` finding: two
different blade geometries now both show meaningful `fom_total` sensitivity
at spacing=0.10m, which sits inside production's own swept spacing range
(0.05-0.10-0.20-0.35-0.60m) and inside the close-spacing region the
2026-07-15 literature pivot identified as where the real azimuth/BVI physics
lives.

## Decision

- **FoM stays the pipeline validation/sanity-check metric** — useful for
  confirming the CFD reproduces literature trends (index angle, offset,
  camber effects), not currently reliable enough to hand to an optimizer at
  the spacings that matter.
- **`thrust_total` remains the MLP's actual training objective**, unchanged
  from the original §2.10 formulation.

This does **not** resolve 4.9's original risk — it explicitly re-accepts it.
Switching to FoM was meant to sidestep the boundary-pinning failure mode of a
power-constrained thrust objective; going back to thrust_total trades that
risk for training on a numerically trustworthy signal instead of one shown to
swing >20% under mesh refinement in the region that matters. The original
4.9 mitigations — tightening the constraint formalization in §4.5, or adding
an explicit penalty/bound on the objective — are therefore still the live
open path to actually closing 4.9, not a change of objective.

## Open follow-ups

1. §4.5 constraint tightening / explicit penalty on `thrust_total`'s power
   constraint — still unaddressed, now the primary path to closing 4.9.
2. Mesh resolution at close spacing (≤0.10m) is under-resolved for at least
   two blade geometries (NACA4412 via `co_rot_meshcheck`, NACA2412 via
   `run_x2td_meshcheck.py`) — a real, uncharacterized-in-magnitude gap in the
   production dataset itself, independent of the objective-function question.
3. `run_sweep.py`'s `_tail_ratio()`/`force_converged()` convergence check has
   a blind spot: an all-zero force history reads as `CONVERGED_TIGHT`
   (ratio=0.0) rather than being flagged. Not yet fixed.
4. A Jeon & Lee (2025) literature-match validation (NACA5412, the closer
   airfoil match for their measured 5% camber / 40% chord section vs. this
   project's default NACA4412) was discussed and recommended but **not
   executed** — only the Qin & Yang / X2TD case above was actually built and
   run.

## Files added

- `cfd_scripts/run_x2td_validation.py`, `cfd_scripts/X2TD_validation.py` —
  literature-match validation sweep and comparison, output at
  `results_X2TD_validation/`.
- `cfd_scripts/run_x2td_meshcheck.py` — mesh-refinement check for the X2TD
  case geometry, output at `9_x2td_meshcheck_sweep/` (WSL, untracked).
