import matplotlib.pyplot as plt
import matplotlib.patches as patches

# Initialize figure with 4 subplots
fig, (ax1, ax2, ax3, ax4) = plt.subplots(1, 4, figsize=(20, 5))
fig.suptitle('MLX90374 Carrier Board + Sensor Placement - 2D Blueprint', fontsize=16, fontweight='bold')

# ==========================================
# 1. Top View (X-Y Plane)
# ==========================================
ax1.set_title("Top View (X-Y Plane)")
ax1.set_xlim(-20, 20)
ax1.set_ylim(-20, 25)
ax1.set_aspect('equal')
ax1.grid(True, linestyle=':', alpha=0.6)
ax1.set_xlabel("X (mm)")
ax1.set_ylabel("Y (mm)")

# Base Outline (35x39 mm)
ax1.add_patch(patches.Rectangle((-17.5, -16.5), 35, 39, fill=False, lw=2, edgecolor='black'))
# Vertical Wall (Top edge, 2mm thick)
ax1.add_patch(patches.Rectangle((-17.5, 20.5), 35, 2, fill=True, color='gray', alpha=0.5))
# Center Hole (14mm diameter)
ax1.add_patch(patches.Circle((0, 0), 7, fill=False, lw=1.5, edgecolor='blue'))
# M2.5 Mounting Holes
for cx, cy in [(0, 9.5), (0, -9.5), (9.5, 0), (-9.5, 0)]:
    ax1.add_patch(patches.Circle((cx, cy), 1.3, fill=True, color='red', alpha=0.7))

# MLX90374 Chip Body (Top-down view: 8mm wide, 1.5mm thick, glued to inside wall)
ax1.add_patch(patches.Rectangle((-4.0, 19.0), 8.0, 1.5, fill=True, color='black', label='MLX90374'))
ax1.legend(loc="lower right", fontsize=8)

# ==========================================
# 2. Front View (X-Z Plane)
# ==========================================
ax2.set_title("Front View (Facing Rotor)")
ax2.set_xlim(-20, 20)
ax2.set_ylim(-2, 40)
ax2.set_aspect('equal')
ax2.grid(True, linestyle=':', alpha=0.6)
ax2.set_xlabel("X (mm)")
ax2.set_ylabel("Z (mm) - Height")

# Base and Wall Outlines
ax2.add_patch(patches.Rectangle((-17.5, 0), 35, 2, fill=True, color='gray', alpha=0.5))
ax2.add_patch(patches.Rectangle((-17.5, 0), 35, 35, fill=False, lw=2, edgecolor='black'))

# Pin Window Cutout (Behind the chip)
ax2.add_patch(patches.Rectangle((-5, 10.7), 10, 2.5, fill=True, color='white', lw=1.5, edgecolor='blue', ls='--'))

# MLX90374 Chip Body (Front face, facing the magnets)
# Sits from Z=10.0 to Z=15.5, perfectly centered
ax2.add_patch(patches.Rectangle((-4.0, 10.0), 8.0, 5.5, fill=True, color='black', alpha=0.85))

# Sensitive Spot (Target at Z=14.0mm)
ax2.add_patch(patches.Circle((0, 14.0), 0.5, fill=True, color='red', zorder=5))
ax2.annotate('Sensitive Spot', xy=(1, 14.0), xytext=(5, 16.0),
             arrowprops=dict(arrowstyle='->', color='red'), color='red', fontsize=9)

# ==========================================
# 3. Right Side View (Y-Z Plane)
# ==========================================
ax3.set_title("Right Side View (Y-Z Plane)")
ax3.set_xlim(12, 25) # Zoomed in slightly to show chip detail
ax3.set_ylim(-2, 40)
ax3.set_aspect('equal')
ax3.grid(True, linestyle=':', alpha=0.6)
ax3.set_xlabel("Y (mm)")
ax3.set_ylabel("Z (mm) - Height")

# Base and Wall Profile
ax3.add_patch(patches.Rectangle((-16.5, 0), 39, 2, fill=True, color='gray', alpha=0.5))
ax3.add_patch(patches.Rectangle((20.5, 2), 2, 33, fill=True, color='gray', alpha=0.5))

# Pin Window Hole Through Wall
ax3.add_patch(patches.Rectangle((20.5, 10.7), 2.0, 2.5, fill=True, color='white', lw=1.5, edgecolor='blue'))

# MLX90374 Chip Body (1.5mm thick, mounted against wall at Y=20.5)
ax3.add_patch(patches.Rectangle((19.0, 10.0), 1.5, 5.5, fill=True, color='black'))
ax3.annotate('MLX Sensor\n(1.5mm thick)', xy=(19.0, 15.0), xytext=(13.0, 18.0),
             arrowprops=dict(arrowstyle='->', color='black'), fontsize=9)

# DMP-4 Pins passing through the window
ax3.add_patch(patches.Rectangle((20.5, 10.7), 3.0, 0.5, fill=True, color='gold'))
ax3.annotate('Pins exiting rear', xy=(23.5, 10.9), xytext=(22.5, 15.0),
             arrowprops=dict(arrowstyle='->', color='olive'), fontsize=9)

# ==========================================
# 4. Back View (X-Z Plane)
# ==========================================
ax4.set_title("Back View (X-Z Plane)")
ax4.set_xlim(20, -20) # Flipped X-axis for rear perspective
ax4.set_ylim(-2, 40)
ax4.set_aspect('equal')
ax4.grid(True, linestyle=':', alpha=0.6)
ax4.set_xlabel("X (mm) - Reversed")
ax4.set_ylabel("Z (mm) - Height")

# The back face of the vertical wall
ax4.add_patch(patches.Rectangle((-17.5, 0), 35, 35, fill=True, color='gray', alpha=0.5))
ax4.add_patch(patches.Rectangle((-17.5, 0), 35, 35, fill=False, lw=2, edgecolor='black'))

# Pin Window Cutout
ax4.add_patch(patches.Rectangle((-5, 10.7), 10, 2.5, fill=True, color='white', lw=1.5, edgecolor='blue'))

# MLX90374 Chip Body (Hidden behind the wall, drawn as dashed outline)
ax4.add_patch(patches.Rectangle((-4.0, 10.0), 8.0, 5.5, fill=False, lw=2, edgecolor='black', ls='--'))
ax4.annotate('Hidden Chip Body', xy=(-4.0, 15.5), xytext=(-12.0, 18.0),
             arrowprops=dict(arrowstyle='->', color='black', ls='--'), fontsize=9)

# 4 Pins sticking out through the window (STD3 configuration = 2.00mm pitch)
pin_x_positions = [3.0, 1.0, -1.0, -3.0]
for px in pin_x_positions:
    ax4.add_patch(patches.Rectangle((px - 0.25, 10.7), 0.5, 0.5, fill=True, color='gold', edgecolor='olive'))

ax4.annotate('4 Pins\n(2.0mm pitch)', xy=(1.0, 10.7), xytext=(8.0, 5.0),
             arrowprops=dict(arrowstyle='->', color='olive'), fontsize=9)

plt.tight_layout()
plt.show()