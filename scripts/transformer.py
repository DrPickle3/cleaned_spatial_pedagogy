import argparse
import csv
import json
import os
from datetime import datetime

import numpy as np


def build_arg_parser():
    """Builds and returns the argument parser for the transform-only script."""
    p = argparse.ArgumentParser(
        description="Apply calibration to a CSV without opening GUI. Input: csv,json. Output: csv"
    )
    p.add_argument('--csv', type=str, required=True,
                   help='CSV file to transform')
    p.add_argument('--json', type=str, required=True,
                   help='Path to calibration_results.json from a previous calibration')
    p.add_argument('--output-dir', type=str,
                   help='Optional output directory. Defaults to a new sibling experiment folder.')
    return p


def load_affine_matrix(calibration_json_path):
    """Loads the affine matrix from a calibration results JSON file."""
    with open(calibration_json_path, encoding='utf-8') as file:
        payload = json.load(file)

    if "calibration_results" in payload:
        payload = payload["calibration_results"]

    if "affine_matrix" not in payload:
        raise KeyError("affine_matrix not found in calibration JSON")

    return np.array(payload["affine_matrix"], dtype=float)


def create_output_folder(base_dir, csv_filename):
    """Creates a new folder for the transformed session."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_name = os.path.splitext(os.path.basename(csv_filename))[0]
    output_name = f"{csv_name}_transformed_{timestamp}"
    output_dir = os.path.join(base_dir, output_name)
    os.makedirs(output_dir, exist_ok=False)
    return output_dir


def apply_affine_to_csv(csv_path, affine_matrix, output_dir):
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
        x_raw = float(row[x_key])
        y_raw = float(row[y_key])
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
    }
    with open(os.path.join(output_dir, "transform_metadata.json"), "w", encoding='utf-8') as file:
        json.dump(metadata, file, indent=2)

    return output_csv


def main():
    """Applies calibration from an existing experiment to a new CSV file."""
    parser = build_arg_parser()
    args = parser.parse_args()

    calibration_json = os.path.abspath(args.json)
    csv_path = os.path.abspath(args.csv)

    if not os.path.exists(calibration_json):
        raise FileNotFoundError(f"Calibration JSON not found: {calibration_json}")
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    affine_matrix = load_affine_matrix(calibration_json)
    base_dir = args.output_dir or os.path.dirname(calibration_json)
    output_dir = create_output_folder(base_dir, csv_path)
    output_csv = apply_affine_to_csv(csv_path, affine_matrix, output_dir)

    print(json.dumps({"output_experiment": output_dir, "output_csv": output_csv}))


if __name__ == '__main__':
    main()
