import argparse
import utils

def build_arg_parser():
    """Build argument parser."""
    p = argparse.ArgumentParser(
        description="Server to receive the data from the Tag, compute its" \
                    "position and write it in a CSV file."
    )    
    p.add_argument('--display', action='store_true',
                    help='Display real time graphic of position and Anchors')
    return p


def main():

    parser = build_arg_parser()
    args = parser.parse_args()

    sock = utils.connect_wifi()
    args.display and utils.screen_init()
    # utils.clear_file()
    utils.load_anchors()
    utils.setup_logging()

    try:
        while True:
            utils.main_loop(sock, args.display)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()