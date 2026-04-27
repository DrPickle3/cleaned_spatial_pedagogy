import argparse
import os
import subprocess
import sys


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CALIBRATION_MAIN = os.path.join(PROJECT_ROOT, "calibration", "main.py")


def build_arg_parser():
    """Builds and returns the argument parser for the calibration-only script."""
    p = argparse.ArgumentParser(
        description="Initial calibration script (GUI). Input: csv,image. Output: experiment folder + json"
    )
    p.add_argument('--csv', type=str, required=True,
                   help='CSV file used during calibration')
    p.add_argument('--image', type=str,
                   help='Optional image preloaded in calibration GUI')
    p.add_argument('--experiment-name', type=str,
                   help='The name for the experiment')
    p.add_argument('--force-overwrite', action='store_true',
                   help='Force overwrite of a non-empty experiment folder')
    return p


def launch_calibration_process(args):
    """Runs the calibration GUI through calibration/main.py and streams its output."""
    if args.csv and not os.path.exists(args.csv):
        raise FileNotFoundError(f"CSV file not found at {args.csv}")
    if args.image and not os.path.exists(args.image):
        raise FileNotFoundError(f"Image file not found at {args.image}")

    cmd = [sys.executable, CALIBRATION_MAIN, "--csv", args.csv]
    if args.image:
        cmd.extend(["--png", args.image])
    if args.experiment_name:
        cmd.extend(["--experiment_name", args.experiment_name])
    if args.force_overwrite:
        cmd.append("--force-overwrite")

    result = subprocess.run(cmd, cwd=os.path.dirname(CALIBRATION_MAIN), text=True)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, cmd)

    return result.returncode


def main():
    """Runs the initial calibration step through the calibration package entry point."""
    parser = build_arg_parser()
    args = parser.parse_args()

    launch_calibration_process(args)


if __name__ == '__main__':
    main()
