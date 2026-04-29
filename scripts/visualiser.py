import argparse
import csv
from datetime import datetime
import logging
import os
import sys

import matplotlib.image as mpimg
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
from matplotlib.patches import Ellipse
from matplotlib.widgets import Button, RangeSlider

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.stats import norm


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import utils


NUM_BINS = 20
MAJOR_CELLS = 10
MINOR_DIV = 5

REAL_RANGE_1D = 3.37
REAL_POS_PRECISION = [2.3622, 1.905]
CHIP_INCERTITUDE = 0.1


def build_arg_parser():
    """Builds and returns the argument parser for the visualization-only script."""
    p = argparse.ArgumentParser(
        description="Visualization-only script. Input: image,csv. Output: interactive viewer"
    )
    p.add_argument('--csv', type=str, default="../logs/positions.csv",
                   help='CSV file to read')
    p.add_argument('--image', type=str,
                   help='Optional background image displayed under the trajectory')
    p.add_argument('--experiment', type=str,
                   help='Optional experiment folder with processed_image and calibrated csv')
    p.add_argument('--heatmap', action='store_true',
                   help='Prints a heatmap of the position')
    p.add_argument('--stops', action='store_true',
                   help='Prints detected stops')
    p.add_argument('--precision', action='store_true',
                   help='Displays precision over the entire log')
    p.add_argument('--trail', type=int, default=10,
                   help='Initial interval length for the range slider')
    p.add_argument('--max_time_diff', type=float, default=0.2,
                   help='Maximum amount of time in seconds between 2 positions')
    return p


def get_positions(csv_filename):
    """Reads x, y and timestamp data from a CSV file."""
    xs, ys, timestamps, float_timestamps = [], [], [], []
    with open(csv_filename, newline='', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        for row in reader:
            try:
                x = float(row.get("x_transformed", row.get("pos_x")))
                y = float(row.get("y_transformed", row.get("pos_y")))

                t = datetime.strptime(row["Timestamp"], "%Y-%m-%d %H:%M:%S.%f")
                float_timestamps.append(t.timestamp())
                timestamps.append(row.get("Timestamp"))
                xs.append(x)
                ys.append(y)
            except (TypeError, ValueError, KeyError):
                continue

    xs, ys = np.array(xs), np.array(ys)
    xs, ys, timestamps, float_timestamps = densify_positions(
        xs, ys, timestamps, float_timestamps
    )

    return xs, ys, timestamps, float_timestamps


def densify_positions(xs, ys, timestamps, float_timestamps, max_dt=0.2):
    """Interpolates positions if the time gap between samples exceeds max_dt."""
    if len(xs) == 0:
        return xs, ys, timestamps, float_timestamps

    new_xs = [xs[0]]
    new_ys = [ys[0]]
    new_ts = [float_timestamps[0]]
    padded_ts = [timestamps[0]]

    for i in range(1, len(xs)):
        x0, y0, t0 = xs[i - 1], ys[i - 1], float_timestamps[i - 1]
        x1, y1, t1 = xs[i], ys[i], float_timestamps[i]
        dt = t1 - t0

        if dt > max_dt:
            steps = int(dt // max_dt)
            for s in range(1, steps + 1):
                r = s / (steps + 1)
                new_xs.append(x0 + r * (x1 - x0))
                new_ys.append(y0 + r * (y1 - y0))
                new_ts.append(t0 + r * dt)
                padded_ts.append(padded_ts[-1])

        new_xs.append(x1)
        new_ys.append(y1)
        new_ts.append(t1)
        padded_ts.append(timestamps[i])

    utils.logger.info("Positions densified")
    return np.array(new_xs), np.array(new_ys), padded_ts, new_ts


def smart_anchors(anchors, csv_filename):
    """Keeps only the anchors that are referenced by the CSV file."""
    if not isinstance(anchors, dict):
        return anchors

    used_anchors = set()
    with open(csv_filename, newline='', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        for row in reader:
            for i in range(1, 5):
                anchor_id = row.get(f"id_{i}")
                if anchor_id:
                    used_anchors.add(anchor_id)
    return {k: v for k, v in anchors.items() if k in used_anchors}


def format_duration(seconds_total):
    """Formats a duration into mm:ss or hh:mm:ss."""
    hours = int(seconds_total // 3600)
    minutes = int((seconds_total % 3600) // 60)
    seconds = int(seconds_total % 60)

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def detect_stops(csv_filename, speed_thresh=0.2, min_duration=30.0):
    """Detects stops based on movement speed threshold and duration."""
    xs, ys, timestamps, float_timestamps = get_positions(csv_filename)

    utils.logger.debug("Stops calculation")
    dt = np.diff(float_timestamps)
    dt[dt == 0] = 1e-6
    vx = np.diff(xs) / dt
    vy = np.diff(ys) / dt
    speed = np.sqrt(vx**2 + vy**2)
    speed = np.append(speed, speed[-1])

    speed_smooth = uniform_filter1d(speed, size=5)
    low = speed_smooth < speed_thresh

    stops = []
    n = len(low)
    i = 0
    while i < n:
        if not low[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and low[j + 1]:
            j += 1

        duration = float_timestamps[j] - float_timestamps[i]
        if duration >= min_duration:
            stops.append({
                "start_frame": i + 1,
                "end_frame": j + 1,
                "x": float(np.mean(xs[i:j + 1])),
                "y": float(np.mean(ys[i:j + 1])),
            })
        i = j + 1

    return xs, ys, float_timestamps, stops


def show_summary_window(csv_filename):
    """Displays a static summary window with stop statistics."""
    xs, ys, float_timestamps, stops = detect_stops(csv_filename)

    fig, ax = plt.subplots(figsize=(6, 4))
    ax.axis('off')
    ax.set_title("Résumé des mesures", fontsize=14, pad=20, weight='bold')

    durations = []
    for s in stops:
        start, end = s["start_frame"], s["end_frame"]
        durations.append(float_timestamps[end - 1] - float_timestamps[start - 1])

    mean_stop = np.mean(durations) if durations else 0
    total_stops = len(durations)
    dist = np.sum(np.sqrt(np.diff(xs)**2 + np.diff(ys)**2)) if len(xs) > 1 else 0

    text = (
        f"**Statistiques**\n"
        f"- Nombre total de points : {len(xs)}\n"
        f"- Distance totale parcourue : {dist:.2f} m\n"
        f"- Nombre d'arrêts : {total_stops}\n"
        f"- Durée moyenne d'arrêt : {mean_stop:.2f} s"
    )

    ax.text(0.05, 0.95, text, va='top', ha='left', fontsize=11, family='monospace')
    plt.tight_layout()
    plt.show(block=False)


def plot_precision_1d(csv_filename):
    """Displays a 1D precision plot for range measurements."""
    xs = []
    with open(csv_filename, newline='', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        for row in reader:
            try:
                xs.append(float(row.get("d1")))
            except (TypeError, ValueError):
                continue

    xs = np.array(xs)
    if len(xs) == 0:
        raise ValueError("No d1 values found in CSV")

    mean_x = np.mean(xs)
    std_x = np.std(xs)

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.set_title("1D Precision Analysis")

    jitter = (np.random.rand(len(xs)) - 0.5) * 0.1
    ax.scatter(xs, jitter, color="blue", alpha=0.6, s=25, label="Measures")

    if std_x > 0:
        x_plot = np.linspace(mean_x - 4 * std_x, mean_x + 4 * std_x, 500)
        pdf = norm.pdf(x_plot, mean_x, std_x)
        pdf = pdf / pdf.max() / 5
        ax.plot(x_plot, pdf, color="red", linewidth=2, label="Gaussian")
        ax.axvspan(mean_x - std_x, mean_x + std_x,
                   color="yellow", alpha=0.15, label="±1σ")
        ax.axvspan(mean_x - 2 * std_x, mean_x + 2 * std_x,
                   color="orange", alpha=0.10, label="±2σ")
        ax.plot(x_plot, pdf, color="none", linewidth=2, label=f"Total measures: {len(xs)}")

    ax.axvline(REAL_RANGE_1D, color="green", linestyle=":", linewidth=2, label="Real position")
    ax.axvline(mean_x, color="gray", linestyle="-", linewidth=2, label=f"Mean = {mean_x:.3f}")
    ax.axvline(mean_x - CHIP_INCERTITUDE, color="purple", linestyle="--", linewidth=2)
    ax.axvline(mean_x + CHIP_INCERTITUDE, color="purple", linestyle="--", linewidth=2, label="Incertitude")
    ax.set_yticks([])
    ax.set_xlabel("Measured range")
    ax.legend()
    ax.grid(True, linestyle=":", alpha=0.5)
    plt.show()


def resolve_visualization_inputs(args):
    """Resolves CSV, image and experiment inputs for the viewer."""
    csv_path = os.path.abspath(args.csv)
    image_path = os.path.abspath(args.image) if args.image else None
    anchors_path = None

    if args.experiment:
        experiment_path = os.path.abspath(args.experiment)
        candidate_csv = os.path.join(experiment_path, "calibrated_points.csv")
        if os.path.exists(candidate_csv):
            csv_path = candidate_csv

        candidate_image = os.path.join(experiment_path, "processed_image.png")
        if os.path.exists(candidate_image):
            image_path = candidate_image

        candidate_anchors = os.path.join(experiment_path, "anchors_calibrated.json")
        if os.path.exists(candidate_anchors):
            anchors_path = candidate_anchors

    return csv_path, image_path, anchors_path


def update_scatter_from_csv(anchors, csv_filename, image_path, args):
    """Displays a dynamic trajectory plot of the tag positions."""
    try:
        img = None
        if image_path and os.path.exists(image_path):
            img = mpimg.imread(image_path)

        xs, ys, timestamps, float_timestamps = get_positions(csv_filename)

        anchor_xs = [coord[0] for coord in anchors.values()]
        anchor_ys = [coord[1] for coord in anchors.values()]

        all_x = np.concatenate([xs, anchor_xs]) if len(anchor_xs) else xs
        all_y = np.concatenate([ys, anchor_ys]) if len(anchor_ys) else ys

        padding = utils.img_padding if img is not None else utils.no_image_padding
        x_min, x_max = all_x.min() - padding, all_x.max() + padding
        y_min, y_max = all_y.min() - padding, all_y.max() + padding

        if args.heatmap:
            fig, (ax_points, ax_heat) = plt.subplots(1, 2, figsize=(12, 6))
            fig.subplots_adjust(bottom=0.25, wspace=0.25)
        else:
            fig, ax_points = plt.subplots()
            fig.subplots_adjust(bottom=0.25)
            ax_heat = None

        def draw_background(target_ax):
            target_ax.set_aspect("equal")
            if img is not None:
                target_ax.imshow(
                    img,
                    extent=[x_min, x_max, y_min, y_max],
                    aspect='equal',
                    origin='lower',
                )

        def apply_axis_frame(target_ax):
            target_ax.set_xlabel("X")
            target_ax.set_ylabel("Y")
            target_ax.set_xlim(x_min, x_max)
            target_ax.set_ylim(y_min, y_max)
            target_ax.invert_yaxis()

            bin_size_x = (x_max - x_min) / MAJOR_CELLS
            bin_size_y = (y_max - y_min) / MAJOR_CELLS
            minor_x = bin_size_x / MINOR_DIV
            minor_y = bin_size_y / MINOR_DIV

            target_ax.set_xticks(np.arange(x_min, x_max + bin_size_x, bin_size_x))
            target_ax.set_yticks(np.arange(y_min, y_max + bin_size_y, bin_size_y))
            target_ax.set_xticks(np.arange(x_min, x_max + minor_x, minor_x), minor=True)
            target_ax.set_yticks(np.arange(y_min, y_max + minor_y, minor_y), minor=True)
            target_ax.grid(which='major', linestyle=':', color='gray', linewidth=1.5, alpha=0.5)
            target_ax.grid(which='minor', linestyle=':', color='gray', linewidth=1, alpha=0.3)

        draw_background(ax_points)

        if args.precision:
            mean_x, mean_y = np.mean(xs), np.mean(ys)
            std_x, std_y = np.std(xs), np.std(ys)
            var_x, var_y = np.var(xs), np.var(ys)
            gaussian_circle = Ellipse(
                (mean_x, mean_y),
                width=4 * std_x,
                height=4 * std_y,
                edgecolor='orange',
                facecolor='none',
                linestyle='--',
                linewidth=1.5,
                label=f"Incertitude (2σ), VarX={var_x:.3f}, VarY={var_y:.3f}",
            )
            ax_points.add_patch(gaussian_circle)
            ax_points.plot(
                [REAL_POS_PRECISION[0]],
                [REAL_POS_PRECISION[1]],
                marker='*',
                color="#30EA30",
                markersize=10,
                linestyle='',
                label="Real position",
            )
            ax_points.plot([mean_x], [mean_y], 'yo', markersize=6, label="Mean position")

        if len(anchor_xs):
            ax_points.scatter(anchor_xs, anchor_ys, c="purple", s=80, marker="X", label="Anchors")

        if args.stops:
            _, _, _, stops_pos = detect_stops(csv_filename)
            stop_xs = [stop["x"] for stop in stops_pos]
            stop_ys = [stop["y"] for stop in stops_pos]
            ax_points.scatter(stop_xs, stop_ys, c="red", s=60, marker="^", label="Stops")

        point, = ax_points.plot([], [], 'go', markersize=6, label="Interval end")
        interval_scatter = ax_points.scatter([], [], c='blue', s=30, label="Interval positions")

        apply_axis_frame(ax_points)
        ax_points.legend()

        if args.heatmap and ax_heat is not None:
            draw_background(ax_heat)

            if len(xs) > 0:
                bin_size_x = (x_max - x_min) / NUM_BINS
                bin_size_y = (y_max - y_min) / NUM_BINS
                x_bins = np.arange(x_min, x_max, bin_size_x)
                y_bins = np.arange(y_min, y_max, bin_size_y)
                heatmap, xedges, yedges = np.histogram2d(xs, ys, bins=[x_bins, y_bins])
                heatmap_seconds = heatmap * args.max_time_diff

                cmap = plt.colormaps["Reds"].copy()
                cmap.set_bad(color="white")

                norm = LogNorm(vmin=0.1, vmax=heatmap_seconds.max())

                im = ax_heat.imshow(
                    heatmap_seconds.T,
                    extent=[xedges[0], xedges[-1], yedges[0], yedges[-1]],
                    origin='lower',
                    cmap=cmap,
                    norm=norm,
                    alpha=0.3,
                    aspect='auto',
                )

                ticks = [1, 5, 10, 30, 60, 120, 300, 600]

                cbar = fig.colorbar(im, ax=ax_heat)
                cbar.set_ticks(ticks)
                cbar.set_ticklabels([str(t) for t in ticks])
                cbar.set_label("Seconds", rotation=270, labelpad=15)

            if len(anchor_xs):
                ax_heat.scatter(anchor_xs, anchor_ys, c="purple", s=80, marker="X", label="Anchors")
                ax_heat.legend()

            apply_axis_frame(ax_heat)
            ax_heat.set_title("Heatmap")

        ax_points.set_title(f"Trajectory map : Frames 1-1/{len(xs)}\n{timestamps[0]} -> {timestamps[0]}")
        total_str = format_duration(float_timestamps[-1] - float_timestamps[0])

        ax_duration = plt.axes([0.25, 0.06, 0.5, 0.03])
        ax_duration.axis("off")
        duration_text = ax_duration.text(0.5, 0.5, f"00:00 - 00:00 / {total_str}", ha="center", va="center", fontsize=10)

        ax_slider = plt.axes([0.25, 0.1, 0.5, 0.03])
        init_end = min(len(xs), max(1, args.trail))
        slider = RangeSlider(
            ax_slider,
            'Frame range',
            1,
            len(xs),
            valinit=(1, init_end),
            valfmt='%d',
        )

        ax_prev = plt.axes([0.1, 0.1, 0.05, 0.03])
        ax_next = plt.axes([0.9, 0.1, 0.05, 0.03])
        btn_prev = Button(ax_prev, "◀")
        btn_next = Button(ax_next, "▶")

        def update(val):
            start_frame, end_frame = slider.val
            start_frame = int(round(start_frame))
            end_frame = int(round(end_frame))
            start_frame = max(1, min(start_frame, len(xs)))
            end_frame = max(1, min(end_frame, len(xs)))
            if start_frame > end_frame:
                start_frame, end_frame = end_frame, start_frame

            selected_x = xs[start_frame - 1:end_frame]
            selected_y = ys[start_frame - 1:end_frame]
            interval_scatter.set_offsets(np.c_[selected_x, selected_y])
            point.set_data([xs[end_frame - 1]], [ys[end_frame - 1]])

            start_duration = float_timestamps[start_frame - 1] - float_timestamps[0]
            end_duration = float_timestamps[end_frame - 1] - float_timestamps[0]
            duration_text.set_text(
                f"{format_duration(start_duration)} - {format_duration(end_duration)} / {total_str}"
            )

            ax_points.set_title(
                f"Trajectory map : Frames {start_frame}-{end_frame}/{len(xs)}\n"
                f"{timestamps[start_frame - 1]} -> {timestamps[end_frame - 1]}"
            )
            fig.canvas.draw_idle()

        slider.on_changed(update)
        update(0)

        def next_frame(event):
            fig.canvas.release_mouse(slider.ax)
            start_frame, end_frame = slider.val
            start_frame = int(round(start_frame))
            end_frame = int(round(end_frame))
            width = max(0, end_frame - start_frame)
            if end_frame < len(xs):
                new_end = end_frame + 1
                new_start = max(1, new_end - width)
                slider.set_val((new_start, new_end))

        def prev_frame(event):
            fig.canvas.release_mouse(slider.ax)
            start_frame, end_frame = slider.val
            start_frame = int(round(start_frame))
            end_frame = int(round(end_frame))
            width = max(0, end_frame - start_frame)
            if start_frame > 1:
                new_start = start_frame - 1
                new_end = min(len(xs), new_start + width)
                slider.set_val((new_start, new_end))

        btn_next.on_clicked(next_frame)
        btn_prev.on_clicked(prev_frame)
        plt.show()

    except KeyboardInterrupt:
        plt.close()


def main():
    """Runs the standalone visualization script."""
    parser = build_arg_parser()
    args = parser.parse_args()

    utils.setup_logging(logging.WARNING)
    anchors = utils.load_anchors()

    csv_path, image_path, anchors_path = resolve_visualization_inputs(args)
    if anchors_path:
        anchors = utils.load_anchors(anchors_path)
    anchors = smart_anchors(anchors, csv_path)

    if args.stops:
        show_summary_window(csv_path)

    if len(anchors) > 1:
        update_scatter_from_csv(anchors, csv_path, image_path, args)
    else:
        plot_precision_1d(csv_path)


if __name__ == '__main__':
    main()
