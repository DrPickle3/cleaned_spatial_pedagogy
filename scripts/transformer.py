import argparse
import csv
import json
import os
import shutil
from datetime import datetime

import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPERIMENTS_ROOT = os.path.join(PROJECT_ROOT, "experiments")


def build_arg_parser():
    """Builds and returns the argument parser for the transform-only script."""
    p = argparse.ArgumentParser(
        description="Apply calibration to a CSV without opening GUI. Input: csv,json. Output: csv"
    )
    p.add_argument('--csv', type=str, required=True,
                   help='CSV file to transform')
    p.add_argument('--experiment', type=str, required=True,
                   help='Experiment folder containing calibration_results.json')
    p.add_argument('--output-dir', type=str,
                   help='Optional output directory. Defaults to a new sibling experiment folder.')
    return p


def load_calibration_payload(calibration_json_path):
    """Loads the calibration JSON payload."""
    with open(calibration_json_path, encoding='utf-8') as file:
        return json.load(file)


def extract_affine_matrix(payload):
    """Extracts the affine matrix from a calibration payload."""
    results = payload.get("calibration_results", payload)
    if "affine_matrix" not in results:
        raise KeyError("affine_matrix not found in calibration JSON")
    return np.array(results["affine_matrix"], dtype=float)


def resolve_path(base_dir, candidate):
    """Resolves a path relative to base_dir when needed."""
    if not candidate:
        return None
    if os.path.isabs(candidate):
        return candidate
    return os.path.abspath(os.path.join(base_dir, candidate))


def load_positions(csv_path):
    """Loads raw position coordinates from a CSV file."""
    points = []
    with open(csv_path, newline='', encoding='utf-8') as infile:
        reader = csv.DictReader(infile)
        for row in reader:
            x_val = row.get("pos_x", row.get("x_transformed"))
            y_val = row.get("pos_y", row.get("y_transformed"))
            if x_val is None or y_val is None:
                continue
            try:
                points.append([float(x_val), float(y_val)])
            except ValueError:
                continue
    return np.array(points, dtype=float)


def load_preprocess_params(calibration_json_path, payload, csv_path=None):
    """Loads or reconstructs the CSV preprocessing parameters."""
    preprocess = payload.get("preprocess") or {}
    if all(k in preprocess for k in ("x_min", "y_min", "scale")):
        return {
            "x_min": float(preprocess["x_min"]),
            "y_min": float(preprocess["y_min"]),
            "scale": float(preprocess["scale"]),
        }

    calibration_dir = os.path.dirname(calibration_json_path)
    scaled_path = os.path.join(calibration_dir, "scaled_coordinates.csv")
    raw_csv_path = resolve_path(calibration_dir, payload.get("csv_file"))

    if os.path.exists(scaled_path):
        scaled_points = np.loadtxt(scaled_path, delimiter=",")
        if scaled_points.size == 0:
            return None
        scaled_points = scaled_points.reshape(-1, 2)
        scaled_min = scaled_points.min(axis=0)
        scaled_max = scaled_points.max(axis=0)
        scaled_range = scaled_max - scaled_min

        if raw_csv_path and os.path.exists(raw_csv_path):
            raw_points = load_positions(raw_csv_path)
            if raw_points.size == 0:
                return None
            raw_points = raw_points.reshape(-1, 2)
            raw_min = raw_points.min(axis=0)
            raw_max = raw_points.max(axis=0)
            raw_range = raw_max - raw_min
            scale_x = scaled_range[0] / raw_range[0] if raw_range[0] > 0 else 1.0
            scale_y = scaled_range[1] / raw_range[1] if raw_range[1] > 0 else 1.0
            scale = min(scale_x, scale_y)
            if scale <= 0:
                scale = 1.0
            x_min = raw_min[0] - (scaled_min[0] / scale if scale else 0.0)
            y_min = raw_min[1] - (scaled_min[1] / scale if scale else 0.0)
            return {"x_min": x_min, "y_min": y_min, "scale": scale}

        if csv_path and os.path.exists(csv_path):
            raw_points = load_positions(csv_path)
            if raw_points.size == 0:
                return None
            raw_points = raw_points.reshape(-1, 2)
            raw_min = raw_points.min(axis=0)
            raw_max = raw_points.max(axis=0)
            raw_range = raw_max - raw_min
            scale_x = scaled_range[0] / raw_range[0] if raw_range[0] > 0 else 1.0
            scale_y = scaled_range[1] / raw_range[1] if raw_range[1] > 0 else 1.0
            scale = min(scale_x, scale_y)
            if scale <= 0:
                scale = 1.0
            x_min = raw_min[0] - (scaled_min[0] / scale if scale else 0.0)
            y_min = raw_min[1] - (scaled_min[1] / scale if scale else 0.0)
            return {"x_min": x_min, "y_min": y_min, "scale": scale}

    return None


def create_output_folder(base_dir, csv_filename):
    """Creates a new folder for the transformed session."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_name = os.path.splitext(os.path.basename(csv_filename))[0]
    output_name = f"{csv_name}_transformed_{timestamp}"
    output_dir = os.path.join(base_dir, output_name)
    os.makedirs(base_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=False)
    return output_dir


def copy_experiment_assets(experiment_dir, output_dir):
    """Copies calibration assets into the output directory when available."""
    copied = []
    for filename in ("anchors_calibrated.json", "processed_image.png"):
        src_path = os.path.join(experiment_dir, filename)
        if os.path.exists(src_path):
            shutil.copy2(src_path, os.path.join(output_dir, filename))
            copied.append(filename)
    return copied


def apply_affine_to_csv(csv_path, affine_matrix, preprocess, output_dir):
    """Applies the affine transform to the CSV and writes calibrated_points.csv."""
    with open(csv_path, newline='', encoding='utf-8') as infile:
        reader = csv.DictReader(infile)
        if reader.fieldnames is None:
            raise ValueError("CSV header missing, cannot transform")

        fieldnames = list(reader.fieldnames)
        rows = list(reader)

    if "x_transformed" not in fieldnames:
        fieldnames.append("x_transformed")
    if "y_transformed" not in fieldnames:
        fieldnames.append("y_transformed")

    for row in rows:
        x_key = "pos_x" if "pos_x" in row else "x_transformed"
        y_key = "pos_y" if "pos_y" in row else "y_transformed"
        if x_key not in row or y_key not in row:
            continue
        x_raw = float(row[x_key])
        y_raw = float(row[y_key])
        if preprocess:
            x_raw = (x_raw - preprocess["x_min"]) * preprocess["scale"]
            y_raw = (y_raw - preprocess["y_min"]) * preprocess["scale"]
        transformed = np.dot(np.array([x_raw, y_raw, 1.0]), affine_matrix[:2, :].T)
        row["x_transformed"] = f"{transformed[0]:.6f}"
        row["y_transformed"] = f"{transformed[1]:.6f}"

    output_csv = os.path.join(output_dir, "calibrated_points.csv")
    with open(output_csv, "w", newline='', encoding='utf-8') as outfile:
        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    metadata = {
        "timestamp": datetime.now().isoformat(),
        "input_csv": os.path.abspath(csv_path),
        "affine_matrix": affine_matrix.tolist(),
        "preprocess": preprocess,
    }
    with open(os.path.join(output_dir, "transform_metadata.json"), "w", encoding='utf-8') as file:
        json.dump(metadata, file, indent=2)

    return output_csv


def main():
    """Applies calibration from an existing experiment to a new CSV file."""
    parser = build_arg_parser()
    args = parser.parse_args()

    experiment_dir = os.path.abspath(args.experiment)
    calibration_json = os.path.join(experiment_dir, "calibration_results.json")
    csv_path = os.path.abspath(args.csv)

    if not os.path.isdir(experiment_dir):
        raise FileNotFoundError(f"Experiment folder not found: {experiment_dir}")
    if not os.path.exists(calibration_json):
        raise FileNotFoundError(
            f"calibration_results.json not found in experiment folder: {experiment_dir}"
        )
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    payload = load_calibration_payload(calibration_json)
    affine_matrix = extract_affine_matrix(payload)
    preprocess = load_preprocess_params(calibration_json, payload, csv_path)
    if preprocess is None:
        raise ValueError(
            "Calibration preprocessing parameters not found. "
            "Re-run calibration or keep scaled_coordinates.csv alongside the calibration JSON."
        )
    base_dir = os.path.abspath(args.output_dir) if args.output_dir else EXPERIMENTS_ROOT
    output_dir = create_output_folder(base_dir, csv_path)
    output_csv = apply_affine_to_csv(csv_path, affine_matrix, preprocess, output_dir)

    copied_files = copy_experiment_assets(experiment_dir, output_dir)
    if copied_files:
        metadata_path = os.path.join(output_dir, "transform_metadata.json")
        with open(metadata_path, encoding="utf-8") as file:
            metadata = json.load(file)
        metadata["copied_assets"] = copied_files
        with open(metadata_path, "w", encoding="utf-8") as file:
            json.dump(metadata, file, indent=2)

    print(json.dumps({"output_experiment": output_dir, "output_csv": output_csv}))


if __name__ == '__main__':
    main()
