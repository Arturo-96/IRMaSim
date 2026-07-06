import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.cm as cm
import numpy as np
import sys
import os

def parse_file(filepath):
    solutions = []
    current = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line == "New solution":
                if current:
                    solutions.append(current)
                current = []
            else:
                parts = line.split(",")
                job_id = int(parts[0])+1
                start = float(parts[1])
                duration = float(parts[2])
                cores = int(parts[3])
                current.append((job_id, start, duration, cores))
    if current:
        solutions.append(current)
    return solutions

def plot_solutions(solutions, output_path):
    n = len(solutions)
    cols = 2
    rows = (n + 1) // cols

    fig, axes = plt.subplots(rows, cols, figsize=(14, rows * 4 + 1))
    fig.patch.set_facecolor("#0f1117")
    axes = np.array(axes).flatten()

    # Collect all unique core values for a consistent colormap
    all_cores = sorted(set(cores for sol in solutions for _, _, _, cores in sol))
    cmap = cm.get_cmap("plasma", len(all_cores))
    core_color = {c: cmap(i) for i, c in enumerate(all_cores)}

    for idx, (sol, ax) in enumerate(zip(solutions, axes)):
        ax.set_facecolor("#1a1d27")
        for spine in ax.spines.values():
            spine.set_edgecolor("#3a3d4d")

        for row_i, (job_id, start, duration, cores) in enumerate(sol):
            color = core_color[cores]
            ax.barh(
                y=row_i,
                width=duration,
                left=start,
                height=0.6,
                color=color,
                edgecolor="white",
                linewidth=0.4,
                alpha=0.9,
            )
            bar_center = start + duration / 2
            ax.text(
                bar_center, row_i,
                f"{cores}c",
                ha="center", va="center",
                fontsize=7, color="white", fontweight="bold"
            )

        ax.set_title(f"Solution {idx + 1}", color="white", fontsize=11, pad=6)
        ax.set_xlabel("Time", color="#aaaacc", fontsize=8)
        ax.set_ylabel("Job ID", color="#aaaacc", fontsize=8)
        ax.tick_params(colors="#aaaacc", labelsize=7)
        ax.set_yticks(range(len(sol)))
        ax.set_yticklabels([f"Job {jid}" for jid, _, _, _ in sol], color="#aaaacc", fontsize=7)

    # Hide unused subplots
    for ax in axes[n:]:
        ax.set_visible(False)

    # Global legend for cores
    legend_patches = [
        mpatches.Patch(color=core_color[c], label=f"{c} cores")
        for c in all_cores
    ]
    fig.legend(
        handles=legend_patches,
        title="Cores",
        title_fontsize=9,
        fontsize=8,
        loc="lower center",
        ncol=len(all_cores),
        framealpha=0.2,
        labelcolor="white",
        facecolor="#1a1d27",
        edgecolor="#3a3d4d",
        bbox_to_anchor=(0.5, 0.01),
    )

    fig.suptitle("Job Scheduling — All Solutions", color="white", fontsize=14, y=1.01)
    plt.tight_layout(rect=[0, 0.06, 1, 1])
    plt.savefig(output_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    print(f"Saved: {output_path}")

if __name__ == "__main__":
    input_file = sys.argv[1] if len(sys.argv) > 1 else "results.log"
    output_file = os.path.splitext(input_file)[0] + "_chart.png"
    solutions = parse_file(input_file)
    print(f"Found {len(solutions)} solutions.")
    plot_solutions(solutions, output_file)
