import argparse
import csv
from datetime import datetime
import json
import logging
import os
import subprocess

import matplotlib.image as mpimg
import matplotlib.cm as cm
import matplotlib.pyplot as plt
from matplotlib.patches import Ellipse
from matplotlib.widgets import Slider, Button                  

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.stats import norm

import utils

# Heatmap
num_bins = 20

# Cells sizes for the grid
major_cells = 10
minor_div = 5

real_range_1d = 3.37
real_pos_precision = [2.3622, 1.905]
chip_incertitude = 0.1 # 10 cm


def build_arg_parser():
    """ Builds and returns the argument parser for CLI options. """
    p = argparse.ArgumentParser(
        description="Writing position of Tag with Anchors in CSV"
    )
    p.add_argument('--heatmap', action='store_true',
                   help='Prints a heatmap of the position')
    p.add_argument('--stops', action='store_true',
                   help='Prints the detected stops')
    p.add_argument('--precision', action='store_true',
                   help='Displays the precision of the entire log')
    p.add_argument('--trail', type=int, default=10,
                    help='Number of previous points to show (e.g. --trail 25)')
    p.add_argument('--max_time_diff', type=float, default=0.2,
                    help='Maximum amount of time in seconds between 2 positions')
    p.add_argument('--csv', type=str, default="../logs/positions.csv",
                    help='CSV file we want to read from')
    p.add_argument('--calibration', action='store_true',
                   help='Calibrate a certain CSV and PNG for visualization' \
                        'You need to save the results to visualize it !!!' \
                        'You also need to match the anchors with the correct' \
                        'image so the the coordinates fit')
    p.add_argument('--experiment', type=str,
                    help='Experiment folder we already have to not do the calibration')
    return p


def get_positions(csv_filename):
    """
    Reads x, y, and timestamp data from the CSV file.

    Args:
        csv_filename (str) : path to the CSV file

    Returns:
        xs (numpy.ndarray) : every x coordinate of each measured position
        ys (numpy.ndarray) : every y coordinate of each measured position
        timestamps (numpy.ndarray) : every timestamps in string
        float_timestamps (numpy.ndarray) : every timestamps in float
    """
    xs, ys, timestamps, float_timestamps = [], [], [], []
    with open(csv_filename, newline='') as file:
        reader = csv.DictReader(file)
        for row in reader:
            try:
                x = float(row.get("x_transformed", row.get("pos_x")))
                y = float(row.get("y_transformed", row.get("pos_y")))

                # For calculations with time
                t = datetime.strptime(row["Timestamp"], "%Y-%m-%d %H:%M:%S.%f")
                float_timestamps.append(t.timestamp())

                # For display
                t = row.get("Timestamp")
                timestamps.append(t)

                xs.append(x)
                ys.append(y)
            except ValueError:
                continue  # skip invalid rows

    xs, ys = np.array(xs), np.array(ys)

    xs, ys, timestamps, float_timestamps = densify_positions(xs, ys, timestamps, float_timestamps)

    return xs, ys, timestamps, float_timestamps


def densify_positions(xs, ys, timestamps, float_timestamps, max_dt=0.2):
    """
    Inserts interpolated positions if the time difference between samples
    exceeds max_dt seconds.

    Args:
        xs (numpy.ndarray) : every x coordinate of each measured position
        ys (numpy.ndarray) : every y coordinate of each measured position
        timestamps (numpy.ndarray) : every timestamps in string
        float_timestamps (numpy.ndarray) : every timestamps in float
        max_dt: (float) : time difference maximum between 2 positions. 
                            Defaults to 0.2 (5/s)

    Returns:
        new_xs (numpy.ndarray) : every x coordinate of each measured position +
                                 padded interpolated positions
        new_ys (numpy.ndarray) : every y coordinate of each measured position +
                                 padded interpolated positions
        padded_ts (numpy.ndarray) : every timestamps in string + 
                                 padded (repeated the last known timestamp)
        new_ts (numpy.ndarray) : every timestamps in float + 
                                 padded (repeated the last known timestamp)
    """
    new_xs = [xs[0]]
    new_ys = [ys[0]]
    new_ts = [float_timestamps[0]]
    padded_ts = [timestamps[0]]

    for i in range(1, len(xs)):
        x0, y0, t0 = xs[i-1], ys[i-1], float_timestamps[i-1]
        x1, y1, t1 = xs[i], ys[i], float_timestamps[i]

        ts1 = timestamps[i]

        dt = t1 - t0

        # number of interpolated steps
        if dt > max_dt:
            steps = int(dt // max_dt)

            for s in range(1, steps + 1):
                r = s / (steps + 1)
                new_xs.append(x0 + r * (x1 - x0))
                new_ys.append(y0 + r * (y1 - y0))
                new_ts.append(t0 + r * dt)
                padded_ts.append(padded_ts[-1])

        # always append real measurement
        new_xs.append(x1)
        new_ys.append(y1)
        new_ts.append(t1)
        padded_ts.append(ts1)

    utils.logger.info("Positions densified")

    return np.array(new_xs), np.array(new_ys), padded_ts, new_ts


def smart_anchors(anchors, csv_filename):
    """
    Returns only the anchors that were used in the CSV file.
    Args:        
        anchors (dictionary{key: anchor id, value: tuple(x, y, z)}) : 
                                                    anchors positions with ids
        csv_filename (str) : path to the CSV file

    Returns:
        anchors (dictionary{key: anchor id, value: tuple(x, y, z)}) : 
                                anchors positions with ids only used in the csv
    """
    used_anchors = set()
    with open(csv_filename, newline='') as file:
        reader = csv.DictReader(file)
        for row in reader:
            try:
                for i in range(1, 5):
                    anchor_id = row.get(f"id_{i}")
                    if anchor_id:
                        used_anchors.add(anchor_id)
            except ValueError:
                continue  # skip invalid rows
    return {k: v for k, v in anchors.items() if k in used_anchors}


def update_scatter_from_csv(anchors, args):
    """
    Main loop : Displays a dynamic trajectory plot of the tag positions.

    Args:        
        anchors (dictionary{key: anchor id, value: tuple(x, y, z)}) : 
                                                    anchors positions with ids
        args (argparse.Namespace) : All command line args are accessible from it
    """
    try :
        fig, ax = plt.subplots()
        plt.subplots_adjust(bottom=0.25)
        ax.set_aspect("equal") # Avoids stretching

        # Image
        if args.calibration:

            if not args.experiment:
                utils.logger.debug("Calibration process")
                result = subprocess.run(
                    ["python", "../calibration/main.py", "--csv", args.csv],
                    capture_output=True, text=True
                )

                full_json = {}
                for line in result.stdout.splitlines():
                    if not line.strip():
                        continue
                    obj = json.loads(line)
                    full_json.update(obj)

                experiment_path = full_json["experiment_path"]
            
            else:
                experiment_path = args.experiment

            img_path = os.path.join(experiment_path, "processed_image.png")

            img = mpimg.imread(img_path)

            # Taking calibrated coordinates for the positions and the anchors
            # Only works if clicked on save (TODO : Make it not crash if not saved)
            args.csv = os.path.join(experiment_path, "calibrated_points.csv")
            new_anchors = os.path.join(experiment_path, "anchors_calibrated.json")

            if os.path.exists(new_anchors):
                anchors = smart_anchors(utils.load_anchors(new_anchors), args.csv)

        xs, ys, timestamps, float_timestamps = get_positions(args.csv)

        # This is better for non moving Tag
        if args.precision:
            utils.logger.debug("Precision calculations")
            mean_x, mean_y = np.mean(xs), np.mean(ys)
            std_x, std_y = np.std(xs), np.std(ys)
            var_x, var_y = np.var(xs), np.var(ys)
            gaussian_circle = Ellipse(
                (mean_x, mean_y),
                width=4*std_x,  # 4*std gives ~95.4% coverage
                height=4*std_y,
                edgecolor='orange',
                facecolor='none',
                linestyle='--',
                linewidth=1.5,
                label=f"Incertitude (2σ), VarX={var_x:.3f}, VarY={var_y:.3f}"
            )

            ax.add_patch(gaussian_circle)

            # Real point + Mean Comparison
            ax.plot(
                [real_pos_precision[0]],
                [real_pos_precision[1]],
                marker='*',
                color="#30EA30",
                markersize=10,
                linestyle='',
                label="Real position"
            )
            ax.plot([mean_x], [mean_y], 'yo', markersize=6, label="Mean position")
        
        anchor_xs = [coord[0] for coord in anchors.values()]
        anchor_ys = [coord[1] for coord in anchors.values()]

        all_x = np.concatenate([xs, anchor_xs])
        all_y = np.concatenate([ys, anchor_ys])

        padding = utils.no_image_padding
        if args.calibration:
            padding = utils.img_padding

        x_min, x_max = all_x.min() - padding, all_x.max() + padding
        y_min, y_max = all_y.min() - padding, all_y.max() + padding

        if args.calibration:
            ax.imshow(img, extent=[x_min, x_max, y_min, y_max], aspect='equal', origin='lower')

        # Anchors
        ax.scatter(anchor_xs, anchor_ys, c="purple", s=80, marker="X", label="Anchors")

        # Stops
        if args.stops:
            useless_xs, useless_ys, useless_ts, stops_pos = detect_stops(args.csv)

            stop_xs = [stop["x"] for stop in stops_pos]
            stop_ys = [stop["y"] for stop in stops_pos]

            ax.scatter(stop_xs, stop_ys, c="red", s=60, marker="^", label="Stops")

        # Dynamic point (moving tag)
        point, = ax.plot([], [], 'go', markersize=6, label="Current position")
        trail_scatter = ax.scatter([], [], c='blue', s=30, label="Past positions")

        # Labels, legend, etc.
        ax.set_xlabel("X")
        ax.set_ylabel("Y")
        ax.set_xlim(x_min, x_max)
        ax.set_ylim(y_min, y_max)
        ax.invert_yaxis()
        ax.legend()

        # Heatmap
        if args.heatmap:
            utils.logger.debug("Heatmap generation")
            # Heatmap
            bin_size_x = (x_max - x_min) / num_bins
            bin_size_y = (y_max - y_min) / num_bins

            x_bins = np.arange(x_min, x_max, bin_size_x)
            y_bins = np.arange(y_min, y_max, bin_size_y)

            # Compute 2D histogram
            heatmap, xedges, yedges = np.histogram2d(xs, ys, bins=[x_bins, y_bins])

            heatmap_seconds = heatmap * args.max_time_diff

            cmap = plt.colormaps["Reds"].copy()
            cmap.set_bad(color="white")   # In case there are invalid values

            # Plot the heatmap UNDER the trail/points
            im = ax.imshow(
                heatmap_seconds.T,
                extent=[xedges[0], xedges[-1], yedges[0], yedges[-1]],
                origin='lower',
                cmap=cmap,
                alpha=0.3,
                aspect='auto'
            )

            cbar = plt.colorbar(im, ax=ax)
            cbar.set_label("Seconds", rotation=270, labelpad=15)

        # Grid lines
        # Major grid spacing
        bin_size_x = (x_max - x_min) / major_cells
        bin_size_y = (y_max - y_min) / major_cells

        # Minor grid spacing
        minor_x = bin_size_x / minor_div
        minor_y = bin_size_y / minor_div

        # Apply major grid
        ax.set_xticks(np.arange(x_min, x_max + bin_size_x, bin_size_x))
        ax.set_yticks(np.arange(y_min, y_max + bin_size_y, bin_size_y))

        # Apply minor grid
        ax.set_xticks(np.arange(x_min, x_max + minor_x, minor_x), minor=True)
        ax.set_yticks(np.arange(y_min, y_max + minor_y, minor_y), minor=True)

        # Draw grids
        ax.grid(which='major', linestyle=':', color='gray', linewidth=1.5, alpha=0.5)
        ax.grid(which='minor', linestyle=':', color='gray', linewidth=1, alpha=0.3)

        # Title
        ax.set_title(f"Trajectory map : Frame 1/{len(xs)}\n{timestamps[0]}")

        ax.set_aspect("equal") # Avoids stretching

        ax_duration = plt.axes([0.25, 0.06, 0.5, 0.03])
        ax_duration.axis("off")

        total_str = format_duration(float_timestamps[-1] - float_timestamps[0])

        duration_text = ax_duration.text(
            0.5, 0.5,
            f"00:00 / {total_str}",
            ha="center", va="center",
            fontsize=10
        )

        ax_slider = plt.axes([0.25, 0.1, 0.5, 0.03])
        slider = Slider(ax_slider, 'Frame', 1, len(xs), valinit=1, valfmt='%d')


        # Buttons for navigation
        ax_prev = plt.axes([0.1, 0.1, 0.05, 0.03])
        ax_next = plt.axes([0.9, 0.1, 0.05, 0.03])
        btn_prev = Button(ax_prev, "◀")
        btn_next = Button(ax_next, "▶")

        def update(val):
            """
            Updates plot when slider range changes.

            Args:        
                val (float) : value of the slider during the callback 
                            (Necessary even if not used)
            """
            end_frame = int(slider.val)
            start_frame = max(1, end_frame - args.trail)

            selected_x = xs[start_frame-1:end_frame]
            selected_y = ys[start_frame-1:end_frame]
            trail_scatter.set_offsets(np.c_[selected_x, selected_y])
            
            # Keep the red point at the end
            point.set_data([xs[end_frame-1]], [ys[end_frame-1]])

            # Compute ghost trail points
            start = max(0, end_frame - 1 - args.trail)
            trail_x = xs[start:end_frame - 1]
            trail_y = ys[start:end_frame - 1]

            # Update the dynamic time duration

            current_duration = float_timestamps[end_frame - 1] - float_timestamps[0]
            cur_str = format_duration(current_duration)

            duration_text.set_text(f"{cur_str} / {total_str}")

            # Fade effect
            n = len(trail_x)
            if n > 0:
                alphas = np.linspace(0.1, 0.8, n)
                colors = [(0, 0, 1, a) for a in alphas]
                trail_scatter.set_offsets(np.c_[trail_x, trail_y][::-1])
                trail_scatter.set_facecolors(colors[::-1])
            else:
                trail_scatter.set_offsets(np.empty((0, 2)))

            ax.set_title(f"Trajectory map : Frame {end_frame}/{len(xs)}\n{timestamps[end_frame - 1]}")
            fig.canvas.draw_idle()

        slider.on_changed(update)

        # Initial frame
        update(0)

        def next_frame(event):
            fig.canvas.release_mouse(slider.ax)
            end_frame = int(slider.val)
            if end_frame < len(xs):
                slider.set_val(end_frame + 1)

        def prev_frame(event):
            fig.canvas.release_mouse(slider.ax)
            end_frame = int(slider.val)
            if end_frame > 1:
                slider.set_val(end_frame - 1)

        btn_next.on_clicked(next_frame)
        btn_prev.on_clicked(prev_frame)

        plt.show()

    except KeyboardInterrupt:
        plt.close()


def plot_precision_1d(csv_filename):
    """
    Reads the single range from CSV and display 1d precision

    Args:
        csv_filename (str) : path to the CSV file
    """
    xs = []
    with open(csv_filename, newline='') as file:
        reader = csv.DictReader(file)
        for row in reader:
            try:
                x = float(row.get("d1"))
                xs.append(x)
            except ValueError:
                continue  # skip invalid rows

    xs = np.array(xs)

    mean_x = np.mean(xs)
    std_x = np.std(xs)
    var_x = np.var(xs)

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.set_title("1D Precision Analysis")

    # Jitter to see the differences
    jitter = (np.random.rand(len(xs)) - 0.5) * 0.1
    ax.scatter(xs, jitter, color="blue", alpha=0.6, s=25, label="Measures")

    # Gaussian curve
    x_plot = np.linspace(mean_x - 4*std_x, mean_x + 4*std_x, 500)
    pdf = norm.pdf(x_plot, mean_x, std_x)

    # Normalize for better visualization
    pdf = pdf / pdf.max() / 5

    ax.plot(x_plot, pdf, color="red", linewidth=2, label="Gaussian")

    # Real measure
    ax.axvline(real_range_1d, color="green", linestyle=":", linewidth=2, label="Real position")

    # Mean and Variances
    ax.axvline(mean_x, color="gray", linestyle="-", linewidth=2, label=f"Mean = {mean_x:.3f}")

    # Incertitude
    ax.axvline(mean_x - chip_incertitude, color="purple", linestyle="--", linewidth=2)
    ax.axvline(mean_x + chip_incertitude, color="purple", linestyle="--", linewidth=2, label=f"Incertitude")

    ax.axvspan(mean_x - std_x, mean_x + std_x,
               color="yellow", alpha=0.15, label="±1σ")

    ax.axvspan(mean_x - 2*std_x, mean_x + 2*std_x,
               color="orange", alpha=0.10, label="±2σ")

    #Invisible line for total measures at the end of legend
    ax.plot(x_plot, pdf, color="none", linewidth=2, label=f"Total measures: {len(xs)}")
    ax.set_yticks([])
    ax.set_xlabel("Measured range")
    ax.legend()
    ax.grid(True, linestyle=":", alpha=0.5)
    plt.show()


def format_duration(seconds_total):
    """
    Format the dynamic timestamp under the slider to have it more readable

    Args:
        seconds_total (float) : seconds from beginning to slider_value

    Returns:
        time (string) : the time in string of format hh:mm:ss
    """
    hours = int(seconds_total // 3600)
    minutes = int((seconds_total % 3600) // 60)
    seconds = int(seconds_total % 60)
    
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    else:
        return f"{minutes:02d}:{seconds:02d}"


def detect_stops(csv_filename, speed_thresh=0.2, min_duration=30.0):
    """
    Detects stops based on movement speed threshold and duration.

    Args:
        csv_filename (str) : path to the CSV file
        speed_thresh (float) : speed treshold to consider a target moving
        min_duration (float) : min pause to count as a stop

    Returns:
        xs (numpy.ndarray) : every x coordinate of each measured position
        ys (numpy.ndarray) : every y coordinate of each measured position
        float_timestamps (numpy.ndarray) : every timestamps in float
        stops (list) : list of dicts each representing a stop using its
                        - starting frame
                        - ending frame
                        - x position
                        - y position
    """
    xs, ys, timestamps, float_timestamps = get_positions(csv_filename)

    utils.logger.debug("Stops calculation")

    dt = np.diff(float_timestamps)
    dt[dt == 0] = 1e-6
    vx = np.diff(xs) / dt
    vy = np.diff(ys) / dt
    speed = np.sqrt(vx**2 + vy**2)
    speed = np.append(speed, speed[-1])  # align length with positions

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
                "x": float(np.mean(xs[i:j+1])),
                "y": float(np.mean(ys[i:j+1])),
            })
        i = j + 1

    return xs, ys, float_timestamps, stops


def show_summary_window(csv_filename):
    """
    Displays a static summary window with stops stats.

    Args:
        csv_filename (str) : path to the CSV file
    """

    xs, ys, float_timestamps, stops = detect_stops(csv_filename)

    fig, ax = plt.subplots(figsize=(6, 4))
    ax.axis('off')
    ax.set_title("Résumé des mesures", fontsize=14, pad=20, weight='bold')

    # Compute stop durations (if provided)
    durations = []
    if stops:
        for s in stops:
            start, end = s["start_frame"], s["end_frame"]
            durations.append(float_timestamps[end-1] - float_timestamps[start-1])

    if durations:
        mean_stop = np.mean(durations)
        total_stops = len(durations)
    else:
        mean_stop = 0
        total_stops = 0

    # Compute total trajectory length
    dist = np.sum(np.sqrt(np.diff(xs)**2 + np.diff(ys)**2))

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


def main():
    """
    Main entry point. Parses args and launches visualization or stop detection.
    """
    parser = build_arg_parser()
    args = parser.parse_args()

    utils.setup_logging(logging.WARNING)

    anchors = utils.load_anchors()
    anchors = smart_anchors(anchors, args.csv)

    if (args.stops):
        show_summary_window(args.csv)

    if len(anchors) > 1:
        update_scatter_from_csv(anchors, args)
    else :
        plot_precision_1d(args.csv)


if __name__ == '__main__':
    main()
