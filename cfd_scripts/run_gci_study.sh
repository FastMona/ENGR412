#!/usr/bin/env bash
# scripts/run_gci_study.sh -- three-resolution grid-convergence (GCI) study for the
# C-T validation mesh, run on your WSL box (this repo has no OpenFOAM in the Claude
# sandbox that authored it -- see analysis/structured_mesh_followup_2026-07-14.md).
#
# Fixes the physical case (single angle, single RPM) and varies ONLY mesh resolution
# via --blade_level, so the resulting thrust/torque differences are attributable to
# discretization error, not to changing the problem being solved. This is the GCI
# study flagged as "unpursued" in the 2026-07-12 investigation log.
#
# Angle choice: theta=8 deg, the reference point used throughout the 07-12 session
# (comments in run_ct_sweep.py cite T~230N @ theta8; most of that investigation's
# numbers are quoted at this angle). RPM: default 650rpm/Mtip=0.228 preset (the
# primary validated regime -- add a second run at 1250rpm yourself if you also want
# the GCI story at the higher Mach number).
#
# Refinement levels: (4,5) coarse, (5,6) current baseline default, (6,7) fine --
# background cell is ~0.4m/2^level, so this is a clean 2x/2x geometric refinement
# ratio (r=2) between successive levels, which is what the Celik et al. (2008) GCI
# procedure in analyze_gci_study.py assumes.
#
# Usage:
#   bash scripts/run_gci_study.sh
#   bash scripts/run_gci_study.sh 12          # different angle
#
# Each level's case + CSV lands under $OUT_ROOT/lvl_<L0>_<L1>/ so nothing overwrites
# your existing caradonnaTung_full_650rpm/ dataset.

set -euo pipefail

ANGLE="${1:-8}"
OUT_ROOT="/home/david/OpenFOAM/ENGR412/gci_study"
LEVELS=("4 5" "5 6" "6 7")

echo "GCI mesh-convergence study -- theta=${ANGLE} deg, full geometry, 650rpm preset"
echo "Levels: ${LEVELS[*]}"
echo "Output: ${OUT_ROOT}/lvl_<L0>_<L1>/"
echo

for lvl in "${LEVELS[@]}"; do
    tag="${lvl// /_}"
    dir="${OUT_ROOT}/lvl_${tag}"
    echo "=== blade_level=(${lvl}) -> ${dir} ==="
    python3 scripts/run_ct_sweep.py \
        --angles "${ANGLE}" \
        --blade_level ${lvl} \
        --sweep_dir "${dir}" \
        --csv "${dir}/ct_results.csv"
    echo
done

echo "All three levels done. Compare with:"
echo "  python3 scripts/analyze_gci_study.py --root ${OUT_ROOT} --angle ${ANGLE}"
