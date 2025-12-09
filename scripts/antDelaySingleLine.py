import logging


def main():

    logging.getLogger().setLevel(logging.INFO) # To see the results

    # Known values
    c = 299_702_547           # m/s (in air)
    tick_duration = 15.65e-12 # s (page 8 https://www.sunnywale.com/uploadfile/2021/1230/DW1000%20User%20Manual_Awin.pdf)
    meters_per_tick = c * tick_duration

    # Distances
    true_distance = 3.37    # real distance between tag and anchor
    measured_distance = 3.181  # measured distance using the tag

    # Tag delay is already calibrated, so assume tau_tag = 0
    tau_tag = 0

    # Compute anchor delay in meters
    tau_anchor = measured_distance - true_distance - tau_tag

    # Convert to ticks
    tau_anchor_ticks = tau_anchor / meters_per_tick

    logging.info(f"Anchor antenna delay: {tau_anchor:.4f} meters, {tau_anchor_ticks:.0f} ticks")


if __name__ == "__main__":
    main()
