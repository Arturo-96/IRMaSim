import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.cm as cm
import numpy as np
import pandas as pd
import sys
import os

def parse_trace(filepath):
    df = pd.read_csv(filepath)
    # Strip whitespace from column names
    df.columns = df.columns.str.strip()
    # Extract job_id from id field (integer part before the dot)
    df['job_id'] = df['id'].apply(lambda x: int(float(str(x).split('.')[0])))
    # Number of cores = number of task rows per job per run
    cores_per_job = df.groupby(['run', 'job_id'])['id'].count().reset_index().rename(columns={'id': 'cores'})
    df = df.merge(cores_per_job, on=['run', 'job_id'])
    # One row per job (collapse tasks)
    jobs = df.groupby(['run', 'job_id']).agg(
        start_time=('start_time', 'first'),
        finish_time=('finish_time', 'first'),
        cores=('cores', 'first'),
    ).reset_index()
    return jobs

def plot_trace(jobs, output_path):
    runs = sorted(jobs['run'].unique())
    n = len(runs)
    cols = min(2, n)
    rows = (n + cols - 1) // cols

    fig, axes = plt.subplots(rows, cols, figsize=(16, rows * 5 + 1), squeeze=False)
    fig.patch.set_facecolor("#0f1117")
    axes = axes.flatten()

    all_cores = sorted(jobs['cores'].unique())
    cmap = cm.get_cmap("plasma", max(len(all_cores), 1))
    core_color = {c: cmap(i) for i, c in enumerate(all_cores)}

    for idx, run in enumerate(runs):
        ax = axes[idx]
        ax.set_facecolor("#1a1d27")
        for spine in ax.spines.values():
            spine.set_edgecolor("#3a3d4d")

        run_jobs = jobs[jobs['run'] == run].sort_values('job_id').reset_index(drop=True)

        for row_i, row in run_jobs.iterrows():
            duration = row['finish_time'] - row['start_time']
            color = core_color[row['cores']]
            ax.barh(
                y=row_i,
                width=max(duration, 1e-9),  # avoid zero-width bars
                left=row['start_time'],
                height=0.6,
                color=color,
                edgecolor="white",
                linewidth=0.4,
                alpha=0.9,
            )
            if duration > 0:
                bar_center = row['start_time'] + duration / 2
                ax.text(
                    bar_center, row_i,
                    f"{int(row['cores'])}c",
                    ha="center", va="center",
                    fontsize=7, color="white", fontweight="bold"
                )

        ax.set_title(f"Run {run}", color="white", fontsize=11, pad=6)
        ax.set_xlabel("Time (s)", color="#aaaacc", fontsize=8)
        ax.set_ylabel("Job ID", color="#aaaacc", fontsize=8)
        ax.tick_params(colors="#aaaacc", labelsize=7)
        ax.set_yticks(range(len(run_jobs)))
        ax.set_yticklabels([f"Job {int(jid)}" for jid in run_jobs['job_id']], color="#aaaacc", fontsize=7)

    for ax in axes[n:]:
        ax.set_visible(False)

    legend_patches = [
        mpatches.Patch(color=core_color[c], label=f"{c} cores")
        for c in all_cores
    ]
    fig.legend(
        handles=legend_patches,
        title="Cores (tasks/job)",
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

    fig.suptitle("Job Scheduling Trace", color="white", fontsize=14, y=1.01)
    plt.tight_layout(rect=[0, 0.06, 1, 1])
    plt.savefig(output_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    print(f"Saved: {output_path}")

if __name__ == "__main__":
    input_file = sys.argv[1] if len(sys.argv) > 1 else "trace.csv"
    output_file = os.path.splitext(input_file)[0] + "_chart.png"
    jobs = parse_trace(input_file)
    print(f"Found {len(jobs['run'].unique())} run(s), {len(jobs)} jobs total.")
    plot_trace(jobs, output_file)
