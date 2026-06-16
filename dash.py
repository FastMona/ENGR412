#!/usr/bin/env python3
"""
dash.py — ENGR412 Coaxial Rotor Project Dashboard
Menu-driven status and control panel.

Run from project root:
  wsl python3 dash.py      # from Windows terminal
  python3 dash.py          # from inside WSL
"""
import csv, os, sys, subprocess, shutil, re
from pathlib import Path
from datetime import datetime

# ── ANSI colours ──────────────────────────────────────────────────────────────
GRN = "\033[92m"; RED = "\033[91m"; YEL = "\033[93m"
CYN = "\033[96m"; BLD = "\033[1m";  DIM = "\033[2m";  RST = "\033[0m"

W = 66  # body width

# ── Path layout ───────────────────────────────────────────────────────────────
ROOT    = Path(__file__).parent.resolve()
SCRIPTS = ROOT / "scripts"
OF      = Path("/home/david/OpenFOAM/ENGR412")
ON_WSL  = Path("/home/david").exists()
LOG_PATH = ROOT / "output.txt"

STL_CHECKS = [
    ("Single-rotor propeller (NACA 4412)",
     OF / "singleRotor/constant/geometry/propeller.stl"),
    ("Upper coaxial (NACA 4412, CCW)",
     OF / "coaxialRotor/constant/geometry/upperPropeller.stl"),
    ("Lower coaxial (NACA 4412, CW)",
     OF / "coaxialRotor/constant/geometry/lowerPropeller.stl"),
]

SWEEP_CHECKS = [
    ("Single rotor",
     OF / "1_single_rotor_sweep/single_rotor_results.csv",                         15),
    ("Co-rotating",
     OF / "2_co_rot_sweep/co_rot_results.csv",                                    525),
    ("Counter-rotating",
     OF / "2_contra_rot_sweep/contra_rot_results.csv",                            525),
    ("C-T full / 650 RPM",
     OF / "caradonnaTung_full_650rpm/ct_results_full_650.csv",                     11),
    ("C-T full / 1250 RPM",
     OF / "caradonnaTung_full_1250rpm/ct_results_full_1250.csv",                    3),
    ("C-T reduced / 650",
     OF / "caradonnaTung_reduced_650rpm/ct_results_reduced_650.csv",               11),
    ("C-T reduced / 1250",
     OF / "caradonnaTung_reduced_1250rpm/ct_results_reduced_1250.csv",              3),
]

EDA_CHECKS = [
    ("Single-rotor",     ROOT / "results_singleRotor",  2),
    ("Co-rotating",      ROOT / "results_2_co_rot",     5),
    ("Counter-rotating", ROOT / "results_2_contra_rot", 5),
]

VAL_CHECKS = [
    ("C-T validation",        ROOT / "results_CT_validation", 4),
    ("C-T Comparison A",      ROOT / "results_CT_appendixA",  2),
]


# ── Clean-up definitions ──────────────────────────────────────────────────────
def _sweep_case_dirs(sweep_dir: Path) -> list:
    if not sweep_dir.exists():
        return []
    return sorted(p for p in sweep_dir.iterdir() if p.is_dir())

def _all_log_files() -> list:
    logs = []
    for d in [OF / "1_single_rotor_sweep",
              OF / "2_co_rot_sweep",
              OF / "2_contra_rot_sweep"]:
        if d.exists():
            for case in d.iterdir():
                if case.is_dir():
                    logs.extend(case.glob("log.*"))
    return logs

def _ct_sweep_dirs(geometry: str) -> list:
    """All theta* case dirs for both RPM variants of the given geometry preset."""
    dirs = []
    for rpm in ("650", "1250"):
        d = OF / f"caradonnaTung_{geometry}_{rpm}rpm"
        if d.exists():
            dirs.extend(sorted(
                p for p in d.iterdir() if p.is_dir() and p.name.startswith("theta")
            ))
    return dirs

def _pycache_dirs() -> list:
    return sorted(ROOT.rglob("__pycache__"))

def _output_log_status() -> str:
    if not LOG_PATH.exists():
        return f"{DIM}file absent{RST}"
    n = sum(1 for _ in open(LOG_PATH, encoding="utf-8"))
    return (f"{YEL}{n} lines{RST}" if n > 100
            else f"{DIM}{n} lines (≤100, nothing to trim){RST}")

def _pycache_status() -> str:
    dirs = _pycache_dirs()
    return (f"{YEL}{len(dirs)} dir(s){RST}" if dirs else f"{DIM}nothing to clean{RST}")

def du_human(path: Path) -> str:
    if not ON_WSL or not path.exists():
        return "?"
    try:
        r = subprocess.run(["du", "-sh", str(path)],
                           capture_output=True, text=True, timeout=120,
                           stdin=subprocess.DEVNULL)
        return r.stdout.split()[0] if r.stdout.strip() else "?"
    except Exception:
        return "?"

def _trim_output_log():
    if not LOG_PATH.exists():
        print(f"\n  {DIM}output.txt does not exist.{RST}")
        pause()
        return
    lines = LOG_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
    n = len(lines)
    if n <= 100:
        print(f"\n  {DIM}output.txt has only {n} lines — nothing to trim.{RST}")
        pause()
        return
    kept = lines[-100:]
    # If TeeLogger is active, close and reopen its file handle around the rewrite
    tl = sys.stdout if isinstance(sys.stdout, TeeLogger) else None
    if tl:
        tl.log.flush()
        tl.log.close()
    LOG_PATH.write_text("".join(kept), encoding="utf-8")
    if tl:
        tl.log = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
    print(f"\n  {GRN}✓ Trimmed output.txt: {n} → 100 lines.{RST}")
    pause()

def _clean_pycache():
    dirs = _pycache_dirs()
    if not dirs:
        print(f"\n  {DIM}No __pycache__ directories found.{RST}")
        pause()
        return
    removed = 0
    for d in dirs:
        try:
            shutil.rmtree(str(d))
            removed += 1
        except Exception as e:
            print(f"  {RED}{e}{RST}")
    print(f"\n  {GRN}✓ Removed {removed} __pycache__ directory/directories.{RST}")
    pause()

CLEAN_DEFS = [
    {
        "key": "a",
        "label": "Sweep log files  (log.* in every case subdir)",
        "small": True,
        "get_targets": _all_log_files,
    },
    {
        "key": "b",
        "label": "Single-rotor  — full reset",
        "small": False,
        "regen": "~30 min  (blockMesh + snappyHexMesh + simpleFoam × 15)",
        "sweep_dir": OF / "1_single_rotor_sweep",
        "get_targets": lambda: _sweep_case_dirs(OF / "1_single_rotor_sweep"),
        "extra_files": [
            OF / "1_single_rotor_sweep/single_rotor_results.csv",
            OF / "singleRotor/constant/geometry/propeller.stl",
        ],
        "extra_dirs": [ROOT / "results_singleRotor"],
    },
    {
        "key": "c",
        "label": "Co-rotating  — full reset",
        "small": False,
        "regen": "~18 h  (blockMesh + snappyHexMesh + simpleFoam × 525)",
        "sweep_dir": OF / "2_co_rot_sweep",
        "get_targets": lambda: _sweep_case_dirs(OF / "2_co_rot_sweep"),
        "extra_files": [
            OF / "2_co_rot_sweep/co_rot_results.csv",
            OF / "coaxialRotor/constant/geometry/upperPropeller.stl",
            OF / "coaxialRotor/constant/geometry/lowerPropeller.stl",
        ],
        "extra_dirs": [ROOT / "results_2_co_rot"],
    },
    {
        "key": "d",
        "label": "Counter-rotating  — full reset",
        "small": False,
        "wsl_only": True,
        "regen": "~18 h  (blockMesh + snappyHexMesh + simpleFoam × 525)",
        "sweep_dir": OF / "2_contra_rot_sweep",
        "get_targets": lambda: _sweep_case_dirs(OF / "2_contra_rot_sweep"),
        "extra_files": [
            OF / "2_contra_rot_sweep/contra_rot_results.csv",
            OF / "coaxialRotor/constant/geometry/upperPropeller.stl",
            OF / "coaxialRotor/constant/geometry/lowerPropeller.stl",
        ],
        "extra_dirs": [ROOT / "results_2_contra_rot"],
    },
    {
        "key": "e",
        "label": "C-T Full geometry — reset  (both 650 + 1250 RPM dirs)",
        "small": False,
        "wsl_only": True,
        "regen": "~5.5 h  (blockMesh+snappy+simpleFoam × 14 cases)",
        "sweep_dir": OF / "caradonnaTung_full_650rpm",
        "get_targets": lambda: _ct_sweep_dirs("full"),
        "extra_files": [
            OF / "caradonnaTung_full_650rpm/ct_results_full_650.csv",
            OF / "caradonnaTung_full_1250rpm/ct_results_full_1250.csv",
        ],
        "extra_dirs": [ROOT / "results_CT_appendixA"],
    },
    {
        "key": "f",
        "label": "C-T Reduced geometry — reset  (both 650 + 1250 RPM dirs)",
        "small": False,
        "wsl_only": True,
        "regen": "~5.5 h  (blockMesh+snappy+simpleFoam × 14 cases)",
        "sweep_dir": OF / "caradonnaTung_reduced_650rpm",
        "get_targets": lambda: _ct_sweep_dirs("reduced"),
        "extra_files": [
            OF / "caradonnaTung_reduced_650rpm/ct_results_reduced_650.csv",
            OF / "caradonnaTung_reduced_1250rpm/ct_results_reduced_1250.csv",
        ],
        "extra_dirs": [ROOT / "results_CT_validation"],
    },
    {
        "key": "g",
        "label": "output.txt  (keep last 100 lines)",
        "small": True,
        "wsl_only": False,
        "get_targets": lambda: [LOG_PATH] if LOG_PATH.exists() else [],
        "get_status": _output_log_status,
        "custom": _trim_output_log,
    },
    {
        "key": "h",
        "label": "__pycache__  (Python bytecode cache)",
        "small": True,
        "wsl_only": False,
        "get_targets": _pycache_dirs,
        "get_status": _pycache_status,
        "custom": _clean_pycache,
    },
]


# ── Utilities ─────────────────────────────────────────────────────────────────
class TeeLogger:
    """
    Replaces sys.stdout so every print() goes to both the terminal and output.txt.
    ANSI colour codes are stripped before writing to the file.
    Each non-blank line in the file is prefixed with a [YYYY-MM-DD HH:MM:SS] stamp.
    Carriage-return overwrites (\r without \n) keep only the final text on that line.
    """
    _ANSI = re.compile(r"\033\[[0-9;]*[A-Za-z]")

    def __init__(self, log_path: Path):
        self.terminal = sys.stdout
        self.log      = open(log_path, "a", encoding="utf-8", buffering=1)
        self._buf     = ""

    def write(self, text: str):
        self.terminal.write(text)
        clean = self._ANSI.sub("", text)
        self._buf += clean
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            # \r in line = terminal overwrite; keep only the last segment
            if "\r" in line:
                line = line.rsplit("\r", 1)[1]
            self.log.write(line + "\n")

    def flush(self):
        self.terminal.flush()
        self.log.flush()

    def fileno(self):
        return self.terminal.fileno()

    def isatty(self) -> bool:
        return self.terminal.isatty()

    def close(self):
        if self._buf:                          # flush any partial line
            self.log.write(self._buf.replace("\r", "") + "\n")
            self._buf = ""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log.write(f"[{ts}] SESSION END\n")
        self.log.close()


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
    ts    = datetime.now().strftime("%d %b %Y  %H:%M")
    title = f"ENGR412 — Coaxial Rotor Dashboard   {ts}"
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
        fname_str = f"  {DIM}{path.name}{RST}" if path.exists() else ""
        print(f"  {tick(done)}  {label:<22}  {col}{pbar(n, expected)}{RST}{fname_str}")
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

    # ── Validation ────────────────────────────────────────────────────────────
    for label, val_dir, expected_figs in VAL_CHECKS:
        n_fig   = fig_count(val_dir)
        has_csv = (val_dir / "validation_summary.csv").exists()
        done    = n_fig >= expected_figs
        if done and has_csv:
            tag = f"{GRN}{n_fig} figures + summary CSV{RST}"
        elif n_fig > 0:
            tag = f"{YEL}{n_fig} figures (exp. only){RST}"
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
                       ("5", "Clean up intermediate files"),
                       ("q", "Quit")]:
        print(f"  {CYN}{key}{RST}  {label}")
    print()


# ── Script runner ─────────────────────────────────────────────────────────────
def run_script(cmd, desc):
    print(f"\n  {BLD}▶ {desc}{RST}")
    print(hline())
    print(f"  {DIM}$ {' '.join(str(c) for c in cmd)}{RST}\n")
    sys.stdout.flush()
    proc = subprocess.Popen(
        [str(c) for c in cmd],
        cwd=str(ROOT),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    for line in proc.stdout or []:
        sys.stdout.write(line)
        sys.stdout.flush()
    proc.wait()
    print()
    print(hline())
    if proc.returncode == 0:
        print(f"  {GRN}✓ Done.{RST}")
    else:
        print(f"  {RED}✗ Exited with code {proc.returncode}.{RST}")
    sys.stdout.flush()
    pause()


def sub_menu(title, opts):
    """Generic sub-menu. opts = list of (key, label, cmd_list | None)."""
    while True:
        clr()
        print(f"\n  {BLD}{title}{RST}")
        print(hline())
        for key, label, _ in opts:
            print(f"  {CYN}{key}{RST}  {label}")
        print(f"  {CYN}0{RST}  Back")
        print()
        ch = prompt()
        if ch == "0":
            return
        for key, label, cmd in opts:
            if ch == key:
                if cmd is None and "collective" in label.lower():
                    deg = input("  Collective angle [deg]: ").strip()
                    cmd = _ct_cmd(deg)

                elif cmd is None and "comparison a" in label.lower():
                    # Choose geometry → look up the matching 1250 RPM CSV + theta5 case dir
                    print(f"\n  {BLD}C-T Comparison A — choose geometry:{RST}")
                    print(f"  {CYN}a{RST}  Full geometry    (caradonnaTung_full_1250rpm/)")
                    print(f"  {CYN}b{RST}  Reduced geometry (caradonnaTung_reduced_1250rpm/)")
                    print(f"  {CYN}0{RST}  Cancel")
                    print()
                    gc = prompt()
                    if gc not in ("a", "b"):
                        break
                    geom = "full" if gc == "a" else "reduced"
                    ct_a_dir  = OF / f"caradonnaTung_{geom}_1250rpm"
                    ct_a_csv  = ct_a_dir / f"ct_results_{geom}_1250.csv"
                    ct_a_case = ct_a_dir / "theta5"
                    if ct_a_csv.exists():
                        csv_path = str(ct_a_csv)
                        print(f"  Using: {csv_path}")
                    else:
                        print(f"  {YEL}{ct_a_csv.name} not found — run a C-T {geom}/1250 sweep first.{RST}")
                        csv_path = input("  Path to CFD results CSV (or Enter to cancel): ").strip()
                        if not csv_path:
                            break
                    cmd = ["python3", str(SCRIPTS / "C-T_comparisonA.py"),
                           "--cfd",      csv_path,
                           "--case_dir", str(ct_a_case),
                           "--outdir",   str(ROOT / "results_CT_appendixA")]

                elif cmd is None and "cfd" in label.lower():
                    # Discover all existing ct_results CSVs and let user pick
                    available = [
                        (geom, rpm)
                        for geom in ("full", "reduced")
                        for rpm  in ("650", "1250")
                        if (OF / f"caradonnaTung_{geom}_{rpm}rpm"
                               / f"ct_results_{geom}_{rpm}.csv").exists()
                    ]
                    if not available:
                        print(f"\n  {YEL}No ct_results CSV found — run a C-T sweep first.{RST}")
                        pause()
                        break
                    if len(available) == 1:
                        geom, rpm = available[0]
                        csv_path = str(OF / f"caradonnaTung_{geom}_{rpm}rpm"
                                          / f"ct_results_{geom}_{rpm}.csv")
                        print(f"  Using: ct_results_{geom}_{rpm}.csv")
                    else:
                        print(f"\n  Available C-T sweep results:")
                        for i, (geom, rpm) in enumerate(available, 1):
                            n = csv_row_count(OF / f"caradonnaTung_{geom}_{rpm}rpm"
                                                 / f"ct_results_{geom}_{rpm}.csv")
                            print(f"  {CYN}{i}{RST}  ct_results_{geom}_{rpm}.csv  "
                                  f"({n} rows)")
                        print(f"  {CYN}0{RST}  Cancel")
                        c2 = prompt()
                        if not c2.isdigit() or int(c2) not in range(1, len(available)+1):
                            break
                        geom, rpm = available[int(c2)-1]
                        csv_path = str(OF / f"caradonnaTung_{geom}_{rpm}rpm"
                                          / f"ct_results_{geom}_{rpm}.csv")
                    cmd = ["python3", str(SCRIPTS / "C-T_validation.py"),
                           "--cfd",    csv_path,
                           "--outdir", str(ROOT / "results_CT_validation")]

                run_script(cmd, label)
                break


# ── Option tables ─────────────────────────────────────────────────────────────
def _stl(*extra):
    return ["python3", str(SCRIPTS / "generate_propeller.py")] + list(extra)

def _ct_cmd(deg, name=None):
    fname = name or f"ctBlade_theta{deg}"
    return _stl("--naca", "0012", "--diameter", "2.286", "--chord", "0.1905",
                "--collective", str(deg), "--root_fraction", "0.20",
                "--rotor_z", "0.0", "--solid_name", fname,
                "--output",
                str(OF / f"caradonnaTung/constant/geometry/{fname}.stl"))

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
     _ct_cmd(8, name="ctBlade")),

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
    ("d", "C-T sweep — Reduced geometry   (RPM → sub-menu)", "CT_REDUCED"),
    ("e", "Dry run — single rotor (preview, no CFD)",
     ["python3", str(SCRIPTS/"run_sweep.py"),
      "--dataset", "single",     "--dry_run"]),
    ("f", "C-T dry-run — Full geometry    (generates files, no solver)",
     ["python3", str(SCRIPTS/"run_ct_sweep.py"), "--geometry", "full", "--dry_run"]),
    ("g", "C-T sweep — Full geometry      (RPM → sub-menu)", "CT_FULL"),
]

# CSV produced by each real sweep (keyed by SWEEP_OPTS key; C-T entries handled dynamically)
SWEEP_CSV_MAP = {
    "a": (OF / "1_single_rotor_sweep/single_rotor_results.csv",    15),
    "b": (OF / "2_co_rot_sweep/co_rot_results.csv",               525),
    "c": (OF / "2_contra_rot_sweep/contra_rot_results.csv",       525),
}

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
    ("d", "Caradonna-Tung validation (experimental data only)",
     ["python3", str(SCRIPTS/"C-T_validation.py"),
      "--outdir", str(ROOT / "results_CT_validation")]),
    ("e", "Caradonna-Tung validation (with CFD results)", None),
    ("f", "C-T Comparison A (Appendix A)", None),
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
    for label, val_dir, _ in VAL_CHECKS:
        n_fig   = fig_count(val_dir)
        has_csv = (val_dir / "validation_summary.csv").exists()
        tag = (f"{GRN}{n_fig} figs + summary CSV{RST}" if has_csv
               else (f"{YEL}{n_fig} figs (exp. only){RST}" if n_fig
                     else f"{RED}not run{RST}"))
        print(f"  {label:<22}  {tag}")

    print()
    pause()


# ── Clean up ──────────────────────────────────────────────────────────────────
def _do_clean(d: dict):
    targets     = d["get_targets"]() if ON_WSL else []
    extra_files = [p for p in d.get("extra_files", []) if p.exists()]
    extra_dirs  = [p for p in d.get("extra_dirs",  []) if p.exists()]

    if not targets and not extra_files and not extra_dirs:
        print(f"\n  {DIM}Nothing to clean.{RST}")
        pause()
        return

    if d["small"]:
        removed = 0
        for t in targets + extra_files:
            try:
                t.unlink()
                removed += 1
            except Exception as e:
                print(f"  {RED}{e}{RST}")
        print(f"\n  {GRN}✓ Removed {removed} file(s).{RST}")
        pause()
        return

    # Large item — show everything that will be deleted, then require "yes"
    print(f"\n  {BLD}{d['label']}{RST}")
    print(f"  {DIM}Measuring disk usage…{RST}", end="\r")
    sys.stdout.flush()
    size = du_human(d["sweep_dir"])

    print(f"  WSL case directories  : {BLD}{size}{RST}  ({len(targets)} dirs)              ")
    print(f"  Time to regenerate    : {d['regen']}")
    all_extras = d.get("extra_files", []) + d.get("extra_dirs", [])
    if all_extras:
        print(f"  Also deleting:")
        for p in all_extras:
            tag = f"{YEL}present{RST}" if p.exists() else f"{DIM}absent{RST}"
            print(f"    {p.name:<44} {tag}")

    print()
    print(f"  {RED}This cannot be undone.{RST}  Type {BLD}yes{RST} to confirm: ", end="")
    sys.stdout.flush()
    ans = input().strip().lower()
    if ans != "yes":
        print(f"  {DIM}Cancelled.{RST}")
        pause()
        return

    errs = 0
    for t in targets + extra_dirs:
        try:
            shutil.rmtree(str(t))
        except Exception as e:
            print(f"  {RED}  {e}{RST}")
            errs += 1
    for f in extra_files:
        try:
            f.unlink()
        except Exception as e:
            print(f"  {RED}  {e}{RST}")
            errs += 1
    n_del = len(targets) + len(extra_files) + len(extra_dirs)
    if errs:
        print(f"  {YEL}Completed with {errs} error(s).{RST}")
    else:
        print(f"  {GRN}✓ Deleted {n_del} items (case dirs + CSV + STL + figures).{RST}")
    pause()


def action_cleanup():
    while True:
        clr()
        print(f"\n  {BLD}CLEAN UP{RST}")
        print(hline())

        for d in CLEAN_DEFS:
            wsl_only = d.get("wsl_only", True)
            if wsl_only and not ON_WSL:
                status = f"{DIM}N/A (WSL only){RST}"
            elif "get_status" in d:
                status = d["get_status"]()
            elif d.get("small"):
                n = len(d["get_targets"]())
                status = (f"{YEL}{n} file(s){RST}" if n else f"{DIM}nothing to clean{RST}")
            else:
                n_dirs  = len(d["get_targets"]()) if ON_WSL else 0
                n_extra = (sum(1 for f  in d.get("extra_files", []) if f.exists()) +
                           sum(1 for dd in d.get("extra_dirs",  []) if dd.exists()))
                if n_dirs == 0 and n_extra == 0:
                    status = f"{DIM}nothing to clean{RST}"
                else:
                    parts = []
                    if n_dirs:  parts.append(f"{n_dirs} case dirs")
                    if n_extra: parts.append(f"{n_extra} result file(s)")
                    status = f"{YEL}{', '.join(parts)}{RST}"
            print(f"  {CYN}{d['key']}{RST}  {d['label']:<52}  {status}")

        print(f"  {CYN}0{RST}  Back")
        print()
        ch = prompt()
        if ch == "0":
            return
        for d in CLEAN_DEFS:
            if ch == d["key"]:
                if "custom" in d:
                    d["custom"]()
                else:
                    _do_clean(d)
                break


# ── Generate STL (always rebuilds) ───────────────────────────────────────────
def _stl_output_path(cmd: list) -> Path | None:
    try:
        return Path(cmd[cmd.index("--output") + 1])
    except (ValueError, IndexError):
        return None


def action_generate():
    while True:
        clr()
        print(f"\n  {BLD}GENERATE PROPELLER STL{RST}")
        print(hline())
        for key, label, _ in STL_OPTS:
            print(f"  {CYN}{key}{RST}  {label}")
        print(f"  {CYN}0{RST}  Back")
        print()
        ch = prompt()
        if ch == "0":
            return
        for key, label, cmd in STL_OPTS:
            if ch == key:
                if cmd is None:
                    deg = input("  Collective angle [deg]: ").strip()
                    cmd = _ct_cmd(deg)
                out = _stl_output_path(cmd)
                if out and out.exists():
                    print(f"\n  {YEL}Rebuilding:{RST} deleting existing {out.name}")
                    out.unlink()
                run_script(cmd, label)
                break


# ── Run CFD sweep (with recalculate / resume prompt) ─────────────────────────
def _ct_row_counts(geometry: str) -> tuple[int, int]:
    """Return (total_found, total_expected) rows across both RPM variants."""
    found, expected = 0, 0
    for rpm, exp in (("650", 11), ("1250", 3)):
        p = OF / f"caradonnaTung_{geometry}_{rpm}rpm" / f"ct_results_{geometry}_{rpm}.csv"
        found    += csv_row_count(p) if p.exists() else 0
        expected += exp
    return found, expected


def action_run_sweep():
    while True:
        clr()
        print(f"\n  {BLD}RUN CFD SWEEP{RST}")
        print(hline())
        for key, label, cmd in SWEEP_OPTS:
            line = f"  {CYN}{key}{RST}  {label}"
            if ON_WSL:
                if key in SWEEP_CSV_MAP:
                    csv_p, exp = SWEEP_CSV_MAP[key]
                    n   = csv_row_count(csv_p) if csv_p.exists() else 0
                    col = GRN if n >= exp else (YEL if n > 0 else DIM)
                    line += f"   {col}{n}/{exp}{RST}"
                elif isinstance(cmd, str) and cmd.startswith("CT_"):
                    geom = cmd[3:].lower()
                    n, exp = _ct_row_counts(geom)
                    col = GRN if n >= exp else (YEL if n > 0 else DIM)
                    line += f"   {col}{n}/{exp}{RST}"
            print(line)
        print(f"  {CYN}0{RST}  Back")
        print()
        ch = prompt()
        if ch == "0":
            return

        for key, label, cmd in SWEEP_OPTS:
            if ch != key:
                continue

            # C-T sentinel: show RPM sub-menu, then rk0 prompt
            if isinstance(cmd, str) and cmd.startswith("CT_"):
                geometry = cmd[3:].lower()   # "CT_REDUCED" → "reduced", "CT_FULL" → "full"
                print(f"\n  {BLD}C-T sweep — {geometry.upper()} geometry{RST}")
                print(hline())
                print(f"  {CYN}a{RST}  ~650 RPM  — 11 angles  (full validation sweep,   ~4 h)")
                print(f"  {CYN}b{RST}  ~1250 RPM —  3 angles  (5° / 8° / 12°,          ~1.5 h)")
                print(f"  {CYN}0{RST}  Cancel")
                print()
                rpm_ch = prompt()
                if rpm_ch not in ("a", "b"):
                    break
                rpm_label, n_exp = ("650", 11) if rpm_ch == "a" else ("1250", 3)
                extra = ([] if rpm_ch == "a"
                         else ["--rpm", "1250", "--angles", "5", "8", "12"])
                sweep_dir = OF / f"caradonnaTung_{geometry}_{rpm_label}rpm"
                csv_p     = sweep_dir / f"ct_results_{geometry}_{rpm_label}.csv"
                n = csv_row_count(csv_p) if csv_p.exists() else 0
                if n > 0:
                    print(f"\n  {YEL}Existing results:{RST} {csv_p.name}  ({n} / {n_exp} rows)")
                    print(f"\n  {CYN}r{RST}  Recalculate — back up CSV and rerun all from scratch")
                    print(f"  {CYN}k{RST}  Keep / Resume — skip completed, add only missing")
                    print(f"  {CYN}0{RST}  Cancel")
                    print()
                    ans = prompt()
                    if ans not in ("r", "k"):
                        print(f"  {DIM}Cancelled.{RST}")
                        pause()
                        break
                    if ans == "r":
                        ts     = datetime.now().strftime("%Y%m%d_%H%M%S")
                        backup = csv_p.parent / f"{csv_p.stem}_backup_{ts}{csv_p.suffix}"
                        if csv_p.exists():
                            csv_p.rename(backup)
                            print(f"\n  {GRN}Backed up:{RST} {backup.name}")
                run_cmd = (["python3", str(SCRIPTS/"run_ct_sweep.py"),
                            "--geometry", geometry,
                            "--sweep_dir", str(sweep_dir),
                            "--csv", str(csv_p)] + extra)
                run_script(run_cmd, f"C-T sweep [{geometry} / {rpm_label} RPM]")
                break

            # Dry-run / setup-check options: run immediately, no CSV logic
            if key not in SWEEP_CSV_MAP:
                run_script(cmd, label)
                break

            csv_p, expected = SWEEP_CSV_MAP[key]
            n = csv_row_count(csv_p) if csv_p.exists() else 0

            if n > 0:
                print(f"\n  {YEL}Existing results:{RST} {csv_p.name}  ({n} / {expected} rows)")
                print(f"\n  {CYN}r{RST}  Recalculate — back up CSV and rerun all cases from scratch")
                print(f"  {CYN}k{RST}  Keep / Resume  — skip completed cases, add only missing")
                print(f"  {CYN}0{RST}  Cancel")
                print()
                ans = prompt()
                if ans not in ("r", "k"):
                    print(f"  {DIM}Cancelled.{RST}")
                    pause()
                    break
                if ans == "r":
                    ts     = datetime.now().strftime("%Y%m%d_%H%M%S")
                    backup = csv_p.parent / f"{csv_p.stem}_backup_{ts}{csv_p.suffix}"
                    csv_p.rename(backup)
                    print(f"\n  {GRN}Backed up:{RST} {backup.name}")

            run_script(cmd, label)
            break


# ── Main loop ─────────────────────────────────────────────────────────────────
def main():
    logger = TeeLogger(LOG_PATH)
    sys.stdout = logger

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
        if   ch == "1": action_generate()
        elif ch == "2": action_run_sweep()
        elif ch == "3": sub_menu("ANALYSE SWEEP RESULTS",    ANALYSE_OPTS)
        elif ch == "4": action_stats()
        elif ch == "5": action_cleanup()
        elif ch in ("q", "quit", "exit"):
            print(f"\n  {DIM}Goodbye.{RST}\n")
            sys.stdout = logger.terminal
            logger.close()
            sys.exit(0)


if __name__ == "__main__":
    main()
