import sys

from .recorder import recorder


def main():
    """
    A minimal CLI for configuring the targeted hrm device from which we will record.
    Usage:
        hrm-recorder config
    """
    if len(sys.argv) < 2:
        print("Usage: hrm-recorder config")
        sys.exit(0)

    cmd = sys.argv[1].lower()

    if cmd == "config":
        hrm = recorder()
        hrm.config()
    else:
        print(f"Unknown command: {cmd}")
