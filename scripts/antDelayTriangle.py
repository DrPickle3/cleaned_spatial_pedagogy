import logging
import numpy as np
from scipy.optimize import minimize


def main():

    logging.getLogger().setLevel(logging.INFO) # To see the results

    # Speed of light and tick duration
    c = 299_702_547  # m/s in the air, not the void
    tick_duration = 15.65e-12  # 15.65 ps average value
    #(page 8 https://www.sunnywale.com/uploadfile/2021/1230/DW1000%20User%20Manual_Awin.pdf)

    meters_per_tick = c * tick_duration  # ~0.00469 m/tick

    # Devices
    devices = ['Tag', 'Anchor1', 'Anchor4']

    # True distances between devices (in meters)
    true_distances = {
        ('Tag', 'Anchor1'): 3.6068,
        ('Tag', 'Anchor4'): 3.8608,
        ('Anchor1', 'Anchor4'): 2.5400
    }

    # Measured distances (in meters) using the server.py script
    measured_distances = {
        ('Tag', 'Anchor1'): 4.092,
        ('Tag', 'Anchor4'): 4.262,
        ('Anchor1', 'Anchor4'): 2.664
    }


    def objective(tau_m):
        """
        The function computing the sum of squared differences between the
        corrected and true distances.

        Args:
            tau_m : (np.ndarray) of size 3 that are the guesses
                    (in ticks) of each device's antenna delay

        Returns:
            float: the error calculated using tau_m.
        """
        error = 0.0
        for (d1, d2), true_d in true_distances.items():
            measured_d = measured_distances[(d1, d2)]
            idx1 = devices.index(d1)
            idx2 = devices.index(d2)
            corrected_d = measured_d - tau_m[idx1] - tau_m[idx2]
            error += (corrected_d - true_d)**2
        return error

    # Initial guess (all zeros)
    initial_guess = np.zeros(len(devices))

    # Minimize
    res = minimize(objective, initial_guess)

    # Optimized delays
    tau_m_opt = res.x   # Optimized variables
    tau_ticks_opt = tau_m_opt / meters_per_tick  # in ticks

    # Print results
    logging.info("Antenna delay corrections:")
    for i, device in enumerate(devices):
        logging.info(f"{device}: {tau_m_opt[i]:.4f} meters, {tau_ticks_opt[i]:.0f} ticks")


if __name__ == "__main__":
    main()
