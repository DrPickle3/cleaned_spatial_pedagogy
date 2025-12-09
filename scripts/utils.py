import csv
import datetime
import json
import logging
import os
import re
import socket
import sys

import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import minimize
import turtle

from zeroconf import ServiceInfo, Zeroconf

TCP_IP = "0.0.0.0" # Accepts everything
TCP_PORT = 5000

meter2pixel = 50   # Ususally always fit in the window (real-time only)
                    # Decrease this number if the anchors are at more than 3-4 meters apart

filename = "../logs/positions.csv" # Will always write in this file

# Put this value to 2 if doing the antennas calibration
minimum_anchors_for_position = 3    # maximum precision

# Small padding for the calibration in post-process
img_padding = 25
no_image_padding = 1

# Global logger for this script
logger = logging.getLogger(__name__)


def load_anchors(config_path="../config.json"):
    """
    Load anchors from a JSON configuration file.

    Args:
        config_path (str, optional): The file path to the JSON config file.
                    Defaults to ../config.json.

    Returns:
        anchors (dictionary{key: anchor id, value: tuple(x, y, z)}) : 
                                                    anchors positions with ids
    """
    if not os.path.exists(config_path):
        logger.error(f"Config file not found: {config_path}")
        return []
    with open(config_path, "r") as f:
        data = json.load(f)

    global anchors
    anchors = {k: tuple(v) for k, v in data["anchors"].items()}

    logger.debug("Anchors loaded")
    logger.debug(anchors)

    return anchors


def on_exit():
    """ Close all matplotlib plots on exit """
    plt.close('all')


def main_loop(sock, display = False):
    """
    Main loop handling TCP data reception, position computing and CSV writing

    Args:
        sock (socket.socket instance): Listening socke, accepts connections
        display (bool) : if True, will display a turtle window with real-time
                         position and Anchors. Default to False
    """
    logger.info(f"Waiting for connection on port {TCP_PORT}")
    conn, addr = sock.accept()
    conn.settimeout(800.0)    # Probably lost Tag connection
    logger.info(f"Connection accepted from {addr}")

    if display:
        global t_anchors, t_tag
    buffer = ""  # reset buffer per connection

    try:
        while True:
            anchors_list, buffer = read_data(conn, buffer)
            ranges = {}

            if display:
                clean(t_anchors)

            for anchor in anchors_list:
                if anchor["A"] in anchors:
                    anchor_range = float(anchor["R"])
                    if anchor_range > 0.0 and anchor_range < 15.0: # Basic validation
                        ranges[anchor["A"]] = anchor_range
                    if display:
                        ax, ay, az = anchors[anchor["A"]]
                        pos_x = -250 + ax * meter2pixel # constants to fit in turtle window
                        pos_y = 150 - ay * meter2pixel
                        draw_uwb_anchor(pos_x, pos_y, anchor["A"], t_anchors)

            anchor_ids = sorted(ranges.keys())[:4]
            distances = [ranges[a] for a in anchor_ids]

            while len(anchor_ids) < 4:
                anchor_ids.append(None)
            while len(distances) < 4:
                distances.append(None)

            if len(ranges) >= minimum_anchors_for_position:
                x = 0.0 # For 1 anchor calculation
                y = 0.0

                if len(ranges) > 1: # Cannot find pos with 1 anchor
                    x, y = tag_pos(ranges, anchors)

                if x == -1 or y == -1:
                    continue

                with open(filename, "a", newline="") as file:
                    writer = csv.writer(file)
                    writer.writerow([
                        len(ranges),
                        *anchor_ids,
                        *distances,
                        x, y, datetime.datetime.now()
                    ])
                if display:
                    clean(t_tag)
                    draw_uwb_tag(x, y, "TAG", t_tag)

    except (ConnectionResetError, BrokenPipeError):
        logger.warning(f"Connection lost from {addr}, waiting for new device...")
        conn.close()
        pass # to try again
    except socket.timeout:
        conn.close()
        logger.warning("Lost connection to the Tag")
        pass # to try again
    except KeyboardInterrupt:
        on_exit()
        conn.close()
        raise KeyboardInterrupt
    

def setup_logging(level = logging.WARNING):
    """
    Make the logger prints in the console during runtime

    Args:
        level (Literal[]) : logging level we want to setup. Defaut to warning
    """
    logger.setLevel(level)

    console_handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter('[%(levelname)s] : %(message)s')

    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)


def tag_pos(ranges, anchors):
    """
    Compute tag position based on distances to known anchors

    Args:
        ranges (dictionary{k: anchor id, v: distance float}): Distances with ids
        anchors (dictionary{key: anchor id, value: tuple(x, y, z)}) : anchors positions with ids

    Returns:
        floats x and y with 3 decimals
    """
    keys = [k for k in ranges if k in anchors]
    anchor_coords = np.array([anchors[k] for k in keys])
    dists = np.array([ranges[k] for k in keys])

    if len(dists) == 2:
        logger.debug("Position with only 2 anchors")

        # Sorting the pairs by the x coord to differentiate left and right
        sorted_pairs = sorted(zip(anchor_coords, dists), key=lambda p: p[0][0])
        left_anchor, left_dist = sorted_pairs[0]
        right_anchor, right_dist = sorted_pairs[1]

        # Third distance for trilateration
        c = np.linalg.norm(right_anchor - left_anchor)

        return tag_pos_2_anchors(right_dist, left_dist, c)

    def error(pos):
        est = np.sqrt(((anchor_coords - pos) ** 2).sum(axis=1))
        return np.sum((est - dists) ** 2)

    # Initial guess = centroid of all the anchors 
    # TODO: For optimization we could keep the last position and use it as the
    # initial guess because its faster if we start near the solution 
    result = minimize(error, x0=np.mean(anchor_coords, axis=0))
    return round(float(result.x[0]), 3), round(float(result.x[1]),3)


def tag_pos_2_anchors(a, b, c):
    r"""
    Estimate 2D tag position using only 2 anchors. It assumes
    c is along the x axis starting at (0, 0). x, y is the Tag's
    coordinates. Using the Law of Cosines

    Args:
        a (float) : represents right side of the triangle
        b (float) : represents left side of the triangle
        c (float) : represents the top side of the triangle (between both anchors)

                    c                   
        AAA1 ------------------ AAA2
         \ cos_a     :           /
          \          :          /
           \         :         /
            \        :        /
             \       :       /
           b  \      :      /  a
               \     :     /
                \    :    /
                 \   :   /
                  \  :  /
                   \ : /
                    \:/
                     V
                    Tag
                    
    Returns:
        floats x and y with 3 decimals
    """
    x=0.0
    y=0.0

    if (a != 0 and b != 0 and c != 0) :
        # Law of cosines
        cos_a = (b * b + c * c - a * a) / (2 * b * c)
        if cos_a * cos_a > 1:   #floating point errors check
            return -1, -1
        x = b * cos_a
        sin_a = (1 - cos_a * cos_a) ** 0.5
        y = b * sin_a

    return round(x, 3), round(y, 3)


def connect_wifi():
    """
    Setup a Wi-Fi TCP server using Zeroconf for discovery

    Returns:
        sock (socket.socket instance): Listening socke, accepts connections
    """

    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)

    # Useful to keep that so we don't have to manually push
    # the new IP address in the Tag.
    info = ServiceInfo(
        "_tcpserver._tcp.local.",             # service type
        "spatialPedagogy._tcpserver._tcp.local.", # service name
        addresses=[socket.inet_aton(local_ip)],
        port=TCP_PORT,
        properties={},
        server=f"spatialPedagogy.local."
    )

    zeroconf = Zeroconf()
    zeroconf.register_service(info)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((TCP_IP, TCP_PORT))
    sock.listen(1)
    return sock


def read_data(conn, buffer):
    """
    Read and parse incoming JSON UWB data from the socket

    Args:
        conn (socket.socket) : connection, we can use it for sending or
                               receiving data
        buffer (str) : accumulated received data

    Returns:
        uwb_list (list of dictionaries) : each dictionary is an anchor with its
                                          id and its range measured
        buffer (str) : cleaned version of the accumulated received data
    """
    try:
        chunk = conn.recv(1024).decode("utf-8")
        buffer += chunk

        uwb_list = []

        # Use regex to extract complete JSON objects
        pattern = r'\{"links":\s*\[.*?\]\}'

        matches = re.findall(pattern, buffer)

        if not matches:
            return uwb_list  # nothing complete yet

        # Keep only the last complete JSON object
        last_json = matches[-1]

        # Remove everything up to after the last complete JSON
        last_index = buffer.rfind(last_json) + len(last_json)
        buffer = buffer[last_index:]

        # Parse it
        uwb_data = json.loads(last_json)
        uwb_list = uwb_data.get("links", []) # [] is default return if != links

        return uwb_list, buffer

    except json.JSONDecodeError as e:
        logger.error("EXCEPTION!", e, last_json if 'last_json' in locals() else buffer)
        return [], buffer
    except socket.timeout:
        raise socket.timeout
    except Exception as e:
        logger.error("EXCEPTION!", e)
        return [], buffer


def clear_file():
    """
    Clear and reinitialize the CSV output file. Writes the header row.
    """
    logger.debug("CSV file cleared")
    with open(filename, "w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow([
            "Nb Anchors", "id_1", "id_2", "id_3", "id_4", "d1", "d2", "d3",
            "d4", "pos_x", "pos_y", "Timestamp"            
        ])


# All the functions under this point are functions to display the turtle window in real-time only
# They are functions directly taken from the Makerfabs showcase code for the Tag and Anchors
# https://github.com/Makerfabs/Makerfabs-ESP32-UWB/blob/main/example/IndoorPositioning/uwb_position_display.py

def screen_init():
    """
    Initialize the turtle-based UI 
    """
    screen = turtle.Screen()
    screen.setup(1200, 800)
    screen.tracer(True)

    global t_anchors, t_tag

    t_anchors = turtle.Turtle()
    t_tag = turtle.Turtle()
    turtle_init(t_anchors)
    turtle_init(t_tag)


def turtle_init(t=turtle):
    """
    Initialize a turtle object
    """
    t.hideturtle()
    t.speed(0)


def fill_cycle(x, y, r, color="black", t=turtle):
    """
    Draw a filled circle on the screen
    """
    t.up()
    t.goto(x, y)
    t.down()
    t.dot(r, color)
    t.up()


def write_txt(x, y, txt, color="black", t=turtle, f=('Arial', 12, 'normal')):
    """
    Write text at a given position
    """

    t.pencolor(color)
    t.up()
    t.goto(x, y)
    t.down()
    t.write(txt, move=False, align='left', font=f)
    t.up()


def clean(t=turtle):
    """
    Clear a turtle layer
    """
    t.clear()


def draw_uwb_anchor(x, y, txt, t):
    """
    Draw a UWB anchor point
    """
    r = 20
    fill_cycle(x, y, r, "green", t)
    write_txt(x + r, y, txt,
              "black",  t, f=('Arial', 16, 'normal'))


def draw_uwb_tag(x, y, txt, t):
    """
    Draw the tag position
    """
    pos_x = -250 + int(x * meter2pixel)
    pos_y = 150 - int(y * meter2pixel)
    r = 20
    fill_cycle(pos_x, pos_y, r, "blue", t)
    write_txt(pos_x, pos_y, txt + ": (" + str(x) + "," + str(y) + ")",
              "black",  t, f=('Arial', 16, 'normal'))
