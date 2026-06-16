"""
generate_propeller.py  —  ENGR412 coaxial rotor project
Generates a 2-blade fixed-pitch propeller as an ASCII STL for OpenFOAM snappyHexMesh.

Default blade geometry (coaxial sweep):
  Airfoil   : NACA 4412
  Diameter  : D (default 1.0 m)
  Pitch     : P (default 0.4 m)  — sets geometric twist via arctan(P/2πr)
  Blades    : 2, separated 180 deg

Caradonna-Tung validation geometry:
  Airfoil   : NACA 0012
  Diameter  : 2.286 m  (R = 1.143 m)
  Chord     : 0.1905 m constant  (--chord 0.1905)
  Collective: 8 deg constant    (--collective 8)
  Root      : 20 % R             (--root_fraction 0.20)

Coordinate system (world frame):
  X, Y  : rotor disk plane (horizontal)
  Z     : thrust axis (up)
  Blade 1 extends along +X from hub.
  Blade 2 is blade 1 rotated 180 deg about Z.

Usage:
  python3 generate_propeller.py [--naca 4412] [--pitch 0.4] [--diameter 1.0]
                                [--chord C]  [--collective DEG]
                                [--root_fraction 0.30]
                                [--rotor_z 5.0] [--mirror_y] [--solid_name NAME]
                                [--azimuth_deg 0] [--output path/to/blade.stl]

Coaxial counter-rotating case:
  Upper rotor (CCW): --rotor_z 5.0  --pitch 0.4  --solid_name upperPropeller
  Lower rotor (CW):  --rotor_z 4.7  --pitch 0.4  --mirror_y  --solid_name lowerPropeller

Caradonna-Tung (theta0=8 deg):
  python3 generate_propeller.py --naca 0012 --diameter 2.286 --chord 0.1905 \
    --collective 8 --root_fraction 0.20 --rotor_z 0.0 \
    --solid_name ctBlade --output .../ctBlade.stl
"""

import argparse
import numpy as np
import os


# ── NACA 4-digit profile ──────────────────────────────────────────────────────
def naca4digit_coords(code, n=50):
    """
    Returns (xu, zu, xl, zl) normalised to chord=1, LE at origin.
    code : 4-digit string or int, e.g. '0012' or 4412.
    z is the thickness axis (out of plane).
    """
    code = str(int(code)).zfill(4)
    M = int(code[0]) / 100.0   # max camber fraction
    P = int(code[1]) / 10.0    # camber position fraction
    T = int(code[2:]) / 100.0  # max thickness fraction

    beta = np.linspace(0, np.pi, n)
    x = 0.5 * (1 - np.cos(beta))

    yt = (T / 0.2) * (0.2969*np.sqrt(x) - 0.1260*x
                      - 0.3516*x**2 + 0.2843*x**3 - 0.1015*x**4)

    if M == 0.0:
        yc  = np.zeros_like(x)
        dyc = np.zeros_like(x)
    else:
        yc = np.where(x < P,
                      (M / P**2) * (2*P*x - x**2),
                      (M / (1-P)**2) * (1 - 2*P + 2*P*x - x**2))
        dyc = np.where(x < P,
                       (2*M / P**2) * (P - x),
                       (2*M / (1-P)**2) * (P - x))

    theta = np.arctan(dyc)
    xu = x  - yt * np.sin(theta)
    zu = yc + yt * np.cos(theta)
    xl = x  + yt * np.sin(theta)
    zl = yc - yt * np.cos(theta)
    return xu, zu, xl, zl


# ── Blade geometry ────────────────────────────────────────────────────────────
def chord_at(r, R, r_root, chord_const=None):
    """Linear taper root→tip, or constant chord if chord_const is given."""
    if chord_const is not None:
        return chord_const
    return np.interp(r, [r_root, R], [0.08, 0.025])

def pitch_angle_at(r, P, collective_deg=None):
    """Geometric pitch angle from pitch distance P, or constant collective."""
    if collective_deg is not None:
        return np.radians(collective_deg)
    return np.arctan(P / (2.0 * np.pi * r))

def build_section(r, R, r_root, P, naca_code=4412,
                  chord_const=None, collective_deg=None, n_pts=50):
    """
    3D airfoil cross-section at span station r.
    Span = X axis, chord ≈ Y axis, thrust = Z axis.
    """
    xu, zu_n, xl, zl_n = naca4digit_coords(naca_code, n_pts)
    c  = chord_at(r, R, r_root, chord_const)
    tw = pitch_angle_at(r, P, collective_deg)

    y_chord   = (xu - 0.25) * c
    z_thick_u = zu_n * c
    z_thick_l = zl_n * c

    y_u =  y_chord * np.cos(tw) - z_thick_u * np.sin(tw)
    z_u =  y_chord * np.sin(tw) + z_thick_u * np.cos(tw)
    y_l =  y_chord * np.cos(tw) - z_thick_l * np.sin(tw)
    z_l =  y_chord * np.sin(tw) + z_thick_l * np.cos(tw)

    y_loop = np.concatenate([y_u, y_l[::-1]])
    z_loop = np.concatenate([z_u, z_l[::-1]])
    x_loop = np.full(2 * n_pts, r)
    return np.column_stack([x_loop, y_loop, z_loop])


# ── Triangulation helpers ─────────────────────────────────────────────────────
def loft(sec_a, sec_b, tris):
    n = len(sec_a)
    for i in range(n):
        j = (i + 1) % n
        tris.append((sec_a[i], sec_a[j], sec_b[j]))
        tris.append((sec_a[i], sec_b[j], sec_b[i]))

def fan_cap(section, tris, flip=False):
    c = section.mean(axis=0)
    n = len(section)
    for i in range(n):
        j = (i + 1) % n
        if flip:
            tris.append((c, section[j], section[i]))
        else:
            tris.append((c, section[i], section[j]))

def generate_blade_tris(R, r_root, P, naca_code=4412,
                        chord_const=None, collective_deg=None,
                        n_span=25, n_pts=50):
    r_stations = np.linspace(r_root, R, n_span)
    sections = [build_section(r, R, r_root, P, naca_code,
                              chord_const, collective_deg, n_pts)
                for r in r_stations]
    tris = []
    for i in range(len(sections) - 1):
        loft(sections[i], sections[i+1], tris)
    fan_cap(sections[0],  tris, flip=True)
    fan_cap(sections[-1], tris, flip=False)
    return tris


# ── Transformations ───────────────────────────────────────────────────────────
def rotate_z(tris, angle_deg):
    a = np.radians(angle_deg)
    Rz = np.array([[np.cos(a), -np.sin(a), 0],
                   [np.sin(a),  np.cos(a), 0],
                   [0,          0,         1]])
    return [(Rz @ p0, Rz @ p1, Rz @ p2) for p0, p1, p2 in tris]

def translate_z(tris, dz):
    d = np.array([0.0, 0.0, dz])
    return [(p0+d, p1+d, p2+d) for p0, p1, p2 in tris]

def mirror_y(tris):
    """Mirror about X-Z plane for counter-rotating (CW) rotor; reverses winding."""
    def my(p):
        return np.array([p[0], -p[1], p[2]])
    return [(my(p0), my(p2), my(p1)) for p0, p1, p2 in tris]


# ── STL writer ────────────────────────────────────────────────────────────────
def normal(p0, p1, p2):
    v1, v2 = p1 - p0, p2 - p0
    n = np.cross(v1, v2)
    L = np.linalg.norm(n)
    return n / L if L > 1e-12 else n

def write_stl(tris, filepath, solid_name="propeller"):
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    with open(filepath, 'w') as f:
        f.write(f"solid {solid_name}\n")
        for tri in tris:
            p0, p1, p2 = (np.asarray(p, dtype=float) for p in tri)
            n = normal(p0, p1, p2)
            f.write(f"  facet normal {n[0]:.6e} {n[1]:.6e} {n[2]:.6e}\n")
            f.write("    outer loop\n")
            for p in (p0, p1, p2):
                f.write(f"      vertex {p[0]:.8e} {p[1]:.8e} {p[2]:.8e}\n")
            f.write("    endloop\n")
            f.write("  endfacet\n")
        f.write(f"endsolid {solid_name}\n")
    print(f"Written {len(tris)} triangles → {filepath}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Generate propeller STL for OpenFOAM")
    ap.add_argument("--naca",          type=str,   default="4412",
                    help="NACA 4-digit code (default: 4412)")
    ap.add_argument("--pitch",         type=float, default=0.4,
                    help="Geometric pitch [m] — sets spanwise twist via arctan(P/2πr) (default 0.4)")
    ap.add_argument("--collective",    type=float, default=None,
                    help="Constant collective pitch angle [deg] — overrides --pitch twist")
    ap.add_argument("--diameter",      type=float, default=1.0,
                    help="Rotor diameter [m] (default 1.0)")
    ap.add_argument("--chord",         type=float, default=None,
                    help="Constant chord [m] — overrides linear taper (default: tapered 0.08→0.025 m)")
    ap.add_argument("--root_fraction", type=float, default=0.30,
                    help="Root cutout as fraction of radius (default 0.30)")
    ap.add_argument("--rotor_z",       type=float, default=5.0,
                    help="Z position of rotor disk centre [m] (default 5.0)")
    ap.add_argument("--output",        type=str,
                    default="/home/david/OpenFOAM/ENGR412/singleRotor/constant/geometry/propeller.stl",
                    help="Output STL path")
    ap.add_argument("--mirror_y",      action="store_true",
                    help="Mirror blade about X-Z plane for counter-rotating (CW) rotor")
    ap.add_argument("--solid_name",    type=str,   default=None,
                    help="STL solid name (defaults to output basename without .stl)")
    ap.add_argument("--azimuth_deg",   type=float, default=0.0,
                    help="Azimuthal index angle [deg]: rotate whole rotor about Z (default 0)")
    ap.add_argument("--n_pts",  type=int, default=50,
                    help="Chordwise profile points per span station (default 50; use 150 for smoother Cp)")
    ap.add_argument("--n_span", type=int, default=25,
                    help="Spanwise lofting stations (default 25)")
    args = ap.parse_args()

    R      = args.diameter / 2.0
    r_root = args.root_fraction * R

    solid = args.solid_name or os.path.splitext(os.path.basename(args.output))[0]

    twist_desc = (f"collective={args.collective} deg (constant)"
                  if args.collective is not None
                  else f"geometric pitch P={args.pitch} m")
    chord_desc = (f"{args.chord} m (constant)"
                  if args.chord is not None
                  else f"tapered 0.08→0.025 m")

    print(f"Generating propeller: NACA {args.naca}  D={args.diameter} m  "
          f"chord={chord_desc}  twist={twist_desc}")
    print(f"  root={r_root:.3f} m ({args.root_fraction*100:.0f}%R)  "
          f"z={args.rotor_z} m  mirror_y={args.mirror_y}  "
          f"azimuth={args.azimuth_deg} deg  solid={solid}")
    print(f"  n_pts={args.n_pts}  n_span={args.n_span}")

    blade1 = generate_blade_tris(R, r_root, args.pitch,
                                 naca_code=args.naca,
                                 chord_const=args.chord,
                                 collective_deg=args.collective,
                                 n_span=args.n_span,
                                 n_pts=args.n_pts)
    blade1 = translate_z(blade1, args.rotor_z)
    blade2 = rotate_z(blade1, 180.0)
    all_tris = blade1 + blade2

    if args.mirror_y:
        all_tris = mirror_y(all_tris)

    if args.azimuth_deg != 0.0:
        all_tris = rotate_z(all_tris, args.azimuth_deg)

    write_stl(all_tris, args.output, solid_name=solid)


if __name__ == "__main__":
    main()
