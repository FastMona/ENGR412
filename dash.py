#!/usr/bin/env python3
"""
dash.py — ENGR412 Coaxial Rotor Project Dashboard
Menu-driven status and control panel.

Run from project root:
  wsl python3 dash.py      # from Windows terminal
  python3 dash.py          # from inside WSL
"""
import csv, os, sys, subprocess
from pathlib import Path

# ── ANSI colours ──────────────────────────────────────────────────────────────
GRN = "\033[92m"; RED = "\033[91m"; YEL = "\033[93m"
CYN = "\033[96m"; BLD = "\033[1m";  DIM = "\033[2m";  RST = "\033[0m"

W = 66  # body width

# ── Path layout ───────────────────────────────────────────────────────────────
ROOT    = Path(__file__).parent.resolve()
SCRIPTS = ROOT / "scripts"
OF      = Path("/home/david/OpenFOAM/ENGR412")
ON_WSL  = Path("/home/david").exists()

STL_CHECKS = [
    ("Single-rotor propeller (NACA 4412)",
     OF / "singleRotor/constant/geometry/propeller.stl"),
    ("Upper coaxial (NACA 4412, CCW)",
     OF / "coaxialRotor/constant/geometry/upperPropeller.stl"),
    ("Lower coaxial (NACA 4412, CW)",
     OF / "coaxialRotor/constant/geometry/lowerPropeller.stl"),
    ("Caradonna-Tung blade (NACA 0012)",
     OF / "caradonnaTung/constant/geometry/ctBlade.stl"),
]

SWEEP_CHECKS = [
    ("Single rotor",
     OF / "1_single_rotor_sweep/single_rotor_results.csv",   15),
    ("Co-rotating",
     OF / "2_co_rot_sweep/co_rot_results.csv",              525),
    ("Counter-rotating",
     OF / "2_contra_rot_sweep/contra_rot_results.csv",      525),
]

EDA_CHECKS = [
    ("Single-rotor",     ROOT / "results_singleRotor",  2),
    ("Co-rotating",      ROOT / "results_2_co_rot",     5),
    ("Counter-rotating", ROOT / "results_2_contra_rot", 5),
]


# ── Utilities ─────────────────────────────────────────────────────────────────
def clr():
    os.system("clear" if os.name == "posix" else "cls")

def csv_row_count(path: Path) -> int:
    try:
        with open(path) as f:
            return max(0, sum(1 for _ in f) - 1)
    except Exception:
        return 0

def fig_count(eda_dir: Path) -> int:
    d = eda_dir / "figures"
    return len(list(d.glob("*.png"))) if d.is_dir() else 0

def tick(ok: bool) -> str:
    return f"{GRN}✓{RST}" if ok else f"{RED}✗{RST}"

def pbar(n, total, w=18) -> str:
    filled = int(w * n / max(total, 1))
    return f"[{'█'*filled}{'░'*(w-filled)}] {n:>3}/{total}"

def hline(char="─"):
    return "  " + char * W

def prompt(msg="  Choice › ") -> str:
    try:
        return input(msg).strip().lower()
    except (KeyboardInterrupt, EOFError):
        print(); sys.exit(0)

def pause():
    input("\n  Press Enter to continue…")

def _col(rows, key):
    try:
        return [float(r[key]) for r in rows if r.get(key) not in ("", None)]
    except Exception:
        return []


# ── Status panel ──────────────────────────────────────────────────────────────
def print_header():
    title = "ENGR412 — Coaxial Rotor Dashboard"
    pad_l = (W - len(title)) // 2
    pad_r = W - len(title) - pad_l
    print(f"\n  ╔{'═'*W}╗")
    print(f"  ║{' '*pad_l}{BLD}{title}{RST}{' '*pad_r}║")
    print(f"  ╚{'═'*W}╝\n")


def print_status():
    # ── STL geometry ──────────────────────────────────────────────────────────
    print(f"  {BLD}STL GEOMETRY{RST}")
    print(hline())
    for label, path in STL_CHECKS:
        if not ON_WSL:
            tag, done = f"{DIM}N/A (WSL only){RST}", False
        elif path.exists():
            tag, done = f"{GRN}generated{RST}  {DIM}{path.name}{RST}", True
        else:
            tag, done = f"{RED}not generated{RST}", False
        print(f"  {tick(done)}  {label:<42} {tag}")
    print()

    # ── CFD sweeps ────────────────────────────────────────────────────────────
    print(f"  {BLD}CFD SWEEPS{RST}")
    print(hline())
    for label, path, expected in SWEEP_CHECKS:
        if not ON_WSL:
            print(f"  {DIM}?{RST}  {label:<22}  {DIM}N/A (WSL only){RST}")
            continue
        n    = csv_row_count(path) if path.exists() else 0
        done = n >= expected
        col  = GRN if done else (YEL if n > 0 else RED)
        print(f"  {tick(done)}  {label:<22}  {col}{pbar(n, expected)}{RST}")
    print()

    # ── EDA / analysis ────────────────────────────────────────────────────────
    print(f"  {BLD}EDA / ANALYSIS{RST}")
    print(hline())
    for label, eda_dir, expected_figs in EDA_CHECKS:
        n_fig   = fig_count(eda_dir)
        has_csv = (eda_dir / "eda_summary.csv").exists()
        done    = has_csv and n_fig >= expected_figs
        if done:
            tag = f"{GRN}{n_fig} figures + summary CSV{RST}"
        elif n_fig > 0:
            tag = f"{YEL}{n_fig} figures, no summary{RST}"
        else:
            tag = f"{RED}not run{RST}"
        print(f"  {tick(done)}  {label:<22}  {tag}")
    print()


def print_main_menu():
    print(hline())
    print(f"  {BLD}ACTIONS{RST}")
    print(hline())
    for key, label in [("1", "Generate propeller STL"),
                       ("2", "Run CFD sweep"),
                       ("3", "Analyse sweep results"),
                       ("4", "Headline statistics"),
                       ("q", "Quit")]:
        print(f"  {CYN}{key}{RST}  {label}")
    print()


# ── Script runner ─────────────────────────────────────────────────────────────
def run_script(cmd, desc):
    print(f"\n  {BLD}▶ {desc}{RST}")
    print(hline())
    print(f"  {DIM}$ {' '.join(str(c) for c in cmd)}{RST}\n")
    result = subprocess.run([str(c) for c in cmd], cwd=str(ROOT))
    print()
    print(hline())
    if result.returncode == 0:
        print(f"  {GRN}✓ Done.{RST}")
    else:
        print(f"  {RED}✗ Exited with code {result.returncode}.{RST}")
    pause()


def sub_menu(title, opts):
    """Generic sub-menu. opts = list of (key, label, cmd_list | None)."""
    while True:
        clr()
        print(f"\n  {BLD}{title}{RST}")
        print(hline())
        for key, label, _ in opts:
            print(f"  {CYN}{key}{RST}  {label}")
        print(f"  {CYN}b{RST}  Back")
        print()
        ch = prompt()
        if ch == "b":
            return
        for key, label, cmd in opts:
            if ch == key:
                if cmd is None:  # C-T custom collective prompt
                    deg = input("  Collective angle [deg]: ").strip()
                    cmd = _ct_cmd(deg)
                run_script(cmd, label)
                break


# ── Option tables ─────────────────────────────────────────────────────────────
def _stl(*extra):
    return ["python3", str(SCRIPTS / "generate_propeller.py")] + list(extra)

def _ct_cmd(deg):
    return _stl("--naca", "0012", "--diameter", "2.286", "--chord", "0.1905",
                "--collective", str(deg), "--root_fraction", "0.20",
                "--rotor_z", "0.0", "--solid_name", f"ctBlade_theta{deg}",
                "--output",
                str(OF / f"caradonnaTung/constant/geometry/ctBlade_theta{deg}.stl"))

STL_OPTS = [
    ("a", "NACA 4412 — single rotor  (D=1 m, P=0.4 m)",
     _stl("--output",
          str(OF / "singleRotor/constant/geometry/propeller.stl"))),

    ("b", "NACA 4412 — upper coaxial (CCW, z=5.0 m)",
     _stl("--rotor_z", "5.0", "--solid_name", "upperPropeller",
          "--output",
          str(OF / "coaxialRotor/constant/geometry/upperPropeller.stl"))),

    ("c", "NACA 4412 — lower coaxial (CW mirror, z=4.7 m)",
     _stl("--rotor_z", "4.7", "--mirror_y", "--solid_name", "lowerPropeller",
          "--output",
          str(OF / "coaxialRotor/constant/geometry/lowerPropeller.stl"))),

    ("d", "NACA 0012 — Caradonna-Tung validation (θ=8°, D=2.286 m)",
     _ct_cmd(8)),

    ("e", "NACA 0012 — C-T custom collective angle…", None),
]

SWEEP_OPTS = [
    ("a", "Single rotor     (15 cases,  ~30 min)",
     ["python3", str(SCRIPTS/"run_sweep.py"),
      "--dataset", "single",     "--parallel", "12"]),
    ("b", "Co-rotating      (525 cases, ~18 h)",
     ["python3", str(SCRIPTS/"run_sweep.py"),
      "--dataset", "co_rot",     "--parallel", "12"]),
    ("c", "Counter-rotating (525 cases, ~18 h)",
     ["python3", str(SCRIPTS/"run_sweep.py"),
      "--dataset", "contra_rot", "--parallel", "12"]),
    ("d", "Dry run — single rotor (preview, no CFD)",
     ["python3", str(SCRIPTS/"run_sweep.py"),
      "--dataset", "single",     "--dry_run"]),
    ("e", "Dry run — co-rotating (preview, no CFD)",
     ["python3", str(SCRIPTS/"run_sweep.py"),
      "--dataset", "co_rot",     "--dry_run"]),
]

ANALYSE_OPTS = [
    ("a", "Single rotor",
     ["python3", str(SCRIPTS/"analyze_sweep.py"),
      "--mode",   "single",
      "--csv",    str(OF / "1_single_rotor_sweep/single_rotor_results.csv"),
      "--outdir", str(ROOT / "results_singleRotor")]),
    ("b", "Co-rotating",
     ["python3", str(SCRIPTS/"analyze_sweep.py"),
      "--csv",    str(OF / "2_co_rot_sweep/co_rot_results.csv"),
      "--outdir", str(ROOT / "results_2_co_rot")]),
    ("c", "Counter-rotating",
     ["python3", str(SCRIPTS/"analyze_sweep.py"),
      "--csv",    str(OF / "2_contra_rot_sweep/contra_rot_results.csv"),
      "--outdir", str(ROOT / "results_2_contra_rot")]),
]


# ── Headline statistics ───────────────────────────────────────────────────────
def action_stats():
    clr()
    print(f"\n  {BLD}HEADLINE STATISTICS{RST}")

    # Single rotor ─────────────────────────────────────────────────────────────
    sr_path = OF / "1_single_rotor_sweep/single_rotor_results.csv"
    print(f"\n  {BLD}Single Rotor  (NACA 4412, D=1 m){RST}")
    print(hline())
    if sr_path.exists():
        with open(sr_path) as f:
            rows = list(csv.DictReader(f))
        thrust = _col(rows, "thrust_N");  fom = _col(rows, "fom")
        best   = max(rows, key=lambda r: float(r.get("fom", 0)))
        print(f"  Cases   : {len(rows)}")
        if thrust: print(f"  Thrust  : {min(thrust):.2f} – {max(thrust):.2f} N")
        if fom:    print(f"  FOM     : {min(fom):.4f} – {max(fom):.4f}")
        print(f"  Best FOM: {best.get('case_id','')}  "
              f"RPM={best.get('rpm','')}  pitch={best.get('pitch','')} m  "
              f"FOM={float(best.get('fom', 0)):.4f}")
    else:
        print(f"  {DIM}CSV not found on WSL filesystem{RST}")

    # Co-rotating ──────────────────────────────────────────────────────────────
    co_path = OF / "2_co_rot_sweep/co_rot_results.csv"
    print(f"\n  {BLD}Co-rotating Coaxial  (NACA 4412){RST}")
    print(hline())
    if co_path.exists():
        with open(co_path) as f:
            all_rows = list(csv.DictReader(f))
        rows = [r for r in all_rows
                if r.get("counter_rotating", "").strip().lower()
                in ("false", "0", "")]
        thrust = _col(rows, "thrust_total_N")
        fom    = _col(rows, "fom_total")
        print(f"  Cases   : {len(rows)} co-rotating  ({len(all_rows)} total in file)")
        if thrust: print(f"  Thrust  : {min(thrust):.2f} – {max(thrust):.2f} N")
        if fom:
            best = max(rows, key=lambda r: float(r.get("fom_total", 0)))
            print(f"  FOM     : {min(fom):.4f} – {max(fom):.4f}")
            print(f"  Best FOM: {best.get('case_id','')}  "
                  f"spacing={best.get('spacing_m','')} m  "
                  f"az={best.get('azimuth_deg','')}°  "
                  f"rpm_l={best.get('rpm_lower','')}  "
                  f"FOM={float(best.get('fom_total', 0)):.4f}")
    else:
        print(f"  {DIM}CSV not found on WSL filesystem{RST}")

    # Counter-rotating ─────────────────────────────────────────────────────────
    contra_path = OF / "2_contra_rot_sweep/contra_rot_results.csv"
    n_contra = csv_row_count(contra_path) if contra_path.exists() else 0
    print(f"\n  {BLD}Counter-rotating Coaxial{RST}")
    print(hline())
    col = GRN if n_contra >= 525 else (YEL if n_contra > 0 else RED)
    print(f"  Cases completed: {col}{pbar(n_contra, 525)}{RST}")

    # EDA outputs ──────────────────────────────────────────────────────────────
    print(f"\n  {BLD}EDA Outputs{RST}")
    print(hline())
    for label, eda_dir, _ in EDA_CHECKS:
        n_fig   = fig_count(eda_dir)
        has_csv = (eda_dir / "eda_summary.csv").exists()
        tag = (f"{GRN}{n_fig} figs + summary CSV{RST}" if has_csv
               else (f"{YEL}{n_fig} figs, no summary{RST}" if n_fig
                     else f"{RED}not run{RST}"))
        print(f"  {label:<22}  {tag}")

    print()
    pause()


# ── Main loop ─────────────────────────────────────────────────────────────────
def main():
    if not ON_WSL:
        clr()
        print(f"\n  {YEL}Warning:{RST} WSL filesystem not detected.")
        print(f"  CFD sweep and STL status checks require running from inside WSL.")
        print(f"  {DIM}Try:  wsl python3 dash.py{RST}\n")
        pause()

    while True:
        clr()
        print_header()
        print_status()
        print_main_menu()
        ch = prompt()
        if   ch == "1": sub_menu("GENERATE PROPELLER STL",   STL_OPTS)
        elif ch == "2": sub_menu("RUN CFD SWEEP",            SWEEP_OPTS)
        elif ch == "3": sub_menu("ANALYSE SWEEP RESULTS",    ANALYSE_OPTS)
        elif ch == "4": action_stats()
        elif ch in ("q", "quit", "exit"):
            print(f"\n  {DIM}Goodbye.{RST}\n"); sys.exit(0)


if __name__ == "__main__":
    main()
