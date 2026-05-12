"""
generate_propeller.py  —  ENGR412 coaxial rotor project
Generates a 2-blade fixed-pitch propeller as an ASCII STL for OpenFOAM snappyHexMesh.

Blade geometry:
  Airfoil   : NACA 4412
  Diameter  : D (default 1.0 m)
  Pitch     : P (default 0.4 m)  — adjustable design variable
  Blades    : 2, separated 180 deg
  Rotor z   : centre of rotor disk in world frame (default 5.0 m for upper rotor)

Coordinate system (world frame):
  X, Y  : rotor disk plane (horizontal)
  Z     : thrust axis (up)
  Blade 1 extends along +X from hub.
  Blade 2 is blade 1 rotated 180 deg about Z.

Usage:
  python3 generate_propeller.py [--pitch 0.4] [--diameter 1.0]
                                [--rotor_z 5.0] [--mirror_y] [--solid_name NAME]
                                [--azimuth_deg 0] [--output path/to/blade.stl]

For coaxial counter-rotating case:
  Upper rotor (CCW): --rotor_z 5.0  --pitch 0.4  --solid_name upperPropeller  --output .../upperPropeller.stl
  Lower rotor (CW):  --rotor_z 4.7  --pitch 0.4  --mirror_y  --solid_name lowerPropeller  --output .../lowerPropeller.stl
  (spacing of 0.3 m = 0.3 * D for first simulation)

  --mirror_y mirrors the blade about the X-Z plane so a CW-spinning rotor generates
  upward thrust with the same NACA 4412 profile.
  --azimuth_deg rotates the whole rotor about Z, setting the azimuthal index angle
  between upper and lower blades for MRF steady-state sweeps.
"""

import argparse
import numpy as np
import os

# ── NACA 4412 profile ─────────────────────────────────────────────────────────
def naca4412_coords(n=50):
    """
    Returns (xu, zu_norm, xl, zl_norm) — upper and lower surface normalised to
    chord = 1, leading edge at origin.  z is the out-of-plane (thickness) axis.
    """
    M, P, T = 0.04, 0.4, 0.12
    # Cosine spacing concentrates points near LE and TE
    beta = np.linspace(0, np.pi, n)
    x = 0.5 * (1 - np.cos(beta))

    yt = (T / 0.2) * (0.2969*np.sqrt(x) - 0.1260*x
                      - 0.3516*x**2 + 0.2843*x**3 - 0.1015*x**4)
    yc = np.where(x < P,
                  (M / P**2) * (2*P*x - x**2),
                  (M / (1-P)**2) * (1 - 2*P + 2*P*x - x**2))
    dyc = np.where(x < P,
                   (2*M / P**2) * (P - x),
                   (2*M / (1-P)**2) * (P - x))
    theta = np.arctan(dyc)

    xu = x  - yt * np.sin(theta)
    zu = yc + yt * np.cos(theta)   # upper surface
    xl = x  + yt * np.sin(theta)
    zl = yc - yt * np.cos(theta)   # lower surface
    return xu, zu, xl, zl


# ── Blade geometry ────────────────────────────────────────────────────────────
def chord_at(r, R, r_root):
    """Linear taper: 0.08 m at root, 0.025 m at tip."""
    return np.interp(r, [r_root, R], [0.08, 0.025])

def pitch_angle_at(r, P):
    """Geometric pitch angle: theta = arctan(P / 2*pi*r) [radians]."""
    return np.arctan(P / (2.0 * np.pi * r))

def build_section(r, R, r_root, P, n_pts=50):
    """
    Returns (2*n_pts, 3) array of 3D points tracing the airfoil cross-section
    at span station r.

    In world frame:
      Span direction  = X axis  (blade extends along +X)
      Chord direction = Y axis  (circumferential, positive = blade rotation direction)
      Thrust axis     = Z axis  (positive = up)

    The section profile sits in the Y-Z plane.
    Chord runs primarily in Y; twist tilts it toward Z.
    """
    xu, zu_n, xl, zl_n = naca4412_coords(n_pts)
    c = chord_at(r, R, r_root)
    tw = pitch_angle_at(r, P)

    # Scale: chord in Y, thickness in Z (before twist rotation)
    # Quarter-chord (x=0.25) centred at y=0
    y_chord = (xu - 0.25) * c          # chord-wise, in-plane
    z_thick_u = zu_n * c               # thickness, upper
    z_thick_l = zl_n * c               # thickness, lower

    # Twist rotation about X (span) axis by angle tw
    # Y' =  Y*cos(tw) - Z*sin(tw)
    # Z' =  Y*sin(tw) + Z*cos(tw)
    y_u =  y_chord * np.cos(tw) - z_thick_u * np.sin(tw)
    z_u =  y_chord * np.sin(tw) + z_thick_u * np.cos(tw)
    y_l =  y_chord * np.cos(tw) - z_thick_l * np.sin(tw)
    z_l =  y_chord * np.sin(tw) + z_thick_l * np.cos(tw)

    # Assemble upper (LE→TE) then lower (TE→LE) to form closed loop
    y_loop = np.concatenate([y_u, y_l[::-1]])
    z_loop = np.concatenate([z_u, z_l[::-1]])
    x_loop = np.full(2 * n_pts, r)

    return np.column_stack([x_loop, y_loop, z_loop])


# ── Triangulation helpers ─────────────────────────────────────────────────────
def loft(sec_a, sec_b, tris):
    """Quad-strip loft between two cross-section loops."""
    n = len(sec_a)
    for i in range(n):
        j = (i + 1) % n
        tris.append((sec_a[i], sec_a[j], sec_b[j]))
        tris.append((sec_a[i], sec_b[j], sec_b[i]))

def fan_cap(section, tris, flip=False):
    """Fan triangulation to seal an open end."""
    c = section.mean(axis=0)
    n = len(section)
    for i in range(n):
        j = (i + 1) % n
        if flip:
            tris.append((c, section[j], section[i]))
        else:
            tris.append((c, section[i], section[j]))

def generate_blade_tris(R, r_root, P, n_span=25, n_pts=50):
    """Returns list of triangles [(p0,p1,p2),...] for one blade."""
    r_stations = np.linspace(r_root, R, n_span)
    sections = [build_section(r, R, r_root, P, n_pts) for r in r_stations]
    tris = []
    for i in range(len(sections) - 1):
        loft(sections[i], sections[i+1], tris)
    fan_cap(sections[0],  tris, flip=True)   # root (inward normal)
    fan_cap(sections[-1], tris, flip=False)  # tip  (outward normal)
    return tris


# ── Transformations ───────────────────────────────────────────────────────────
def rotate_z(tris, angle_deg):
    """Rotate triangle list about Z axis."""
    a = np.radians(angle_deg)
    Rz = np.array([[np.cos(a), -np.sin(a), 0],
                   [np.sin(a),  np.cos(a), 0],
                   [0,          0,         1]])
    return [(Rz @ p0, Rz @ p1, Rz @ p2) for p0, p1, p2 in tris]

def translate_z(tris, dz):
    d = np.array([0.0, 0.0, dz])
    return [(p0+d, p1+d, p2+d) for p0, p1, p2 in tris]

def mirror_y(tris):
    """Mirror about X-Z plane (negate Y) for counter-rotating rotor geometry.
    Reverses triangle winding to maintain outward normals after the reflection."""
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
    ap.add_argument("--pitch",    type=float, default=0.4,
                    help="Geometric pitch [m]  (default 0.4)")
    ap.add_argument("--diameter", type=float, default=1.0,
                    help="Rotor diameter [m]  (default 1.0)")
    ap.add_argument("--rotor_z",  type=float, default=5.0,
                    help="Z position of rotor disk centre [m]  (default 5.0)")
    ap.add_argument("--output",      type=str,
                    default="/home/david/OpenFOAM/ENGR412/singleRotor/constant/geometry/propeller.stl",
                    help="Output STL path")
    ap.add_argument("--mirror_y",    action="store_true",
                    help="Mirror blade about X-Z plane for counter-rotating (CW) rotor")
    ap.add_argument("--solid_name",  type=str, default=None,
                    help="STL solid name (defaults to basename of output without .stl)")
    ap.add_argument("--azimuth_deg", type=float, default=0.0,
                    help="Azimuthal index angle [deg]: rotate whole rotor about Z (default 0)")
    args = ap.parse_args()

    R      = args.diameter / 2.0
    r_root = 0.15 * args.diameter

    solid = args.solid_name or os.path.splitext(os.path.basename(args.output))[0]

    print(f"Generating propeller: D={args.diameter}m  P={args.pitch}m  "
          f"z={args.rotor_z}m  root={r_root:.3f}m  mirror_y={args.mirror_y}  "
          f"azimuth={args.azimuth_deg}deg  solid={solid}")
    print(f"Tip pitch angle : {np.degrees(np.arctan(abs(args.pitch)/(2*np.pi*R))):.1f} deg")
    print(f"Root pitch angle: {np.degrees(np.arctan(abs(args.pitch)/(2*np.pi*r_root))):.1f} deg")

    blade1 = generate_blade_tris(R, r_root, args.pitch)
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
