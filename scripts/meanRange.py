import argparse
import csv
import logging
import os

def build_arg_parser():
    """Build argument parser."""

    p = argparse.ArgumentParser(
        description="Reading mean ranges per anchor from CSV"
    )    
    p.add_argument('--csv', type=str, default="../logs/positions.csv",
                    help='CSV file we want to read from')
    return p

def main():
    """ 
    Dynamically reads the CSV to know how many ranges to print.
    The whole CSV has to have the same amount of anchors though.
    You can't have half the measures with 3 anchors and the other 4.
    """
    
    parser = build_arg_parser()
    args = parser.parse_args()
    csv_path = args.csv

    logging.getLogger().setLevel(logging.INFO) # To see the results

    if not os.path.exists(csv_path):
        logging.error(f"File {csv_path} does not exist.")
        return

    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        logging.warning("CSV is empty.")
        return
    
    logging.debug(f"{csv_path} loaded.")

    first_row = rows[0]
    nb_anchors = int(first_row["Nb Anchors"])

    anchor_ranges = [f"d{i+1}" for i in range(nb_anchors)]
    ids = [f"id_{i+1}" for i in range(nb_anchors)]

    dict_ranges_ids = {anchor_ranges[i] : ids[i] for i in range(nb_anchors)}

    anchor_ids = {ids[i] : first_row[ids[i]] for i in range(nb_anchors)}
    anchor_distances = {anchor_ids[id]: [] for id in anchor_ids.keys()}

    for row in rows:
        for distance in anchor_ranges:
            val = row[distance]
            anchor_distances[anchor_ids[dict_ranges_ids[distance]]].append(float(val))

    means = {anchor_id: sum(vals) / len(vals) for anchor_id, vals in anchor_distances.items()}

    # Print results
    for anchor_id, mean_val in means.items():
        logging.info(f"  {anchor_id}: {mean_val:.3f}\n")


if __name__ == "__main__":
    main()
