import json
import os

from bleak import BleakScanner

CONFIG_FILENAME = ".hrm_config.json"


def get_config_path() -> str:
    """Returns the path to the local config file (per-project)."""
    return os.path.join(os.getcwd(), CONFIG_FILENAME)


def load_device_config():
    """Loads device info (address, name) from local JSON file, if it exists."""
    path = get_config_path()
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return None


def save_device_config(address: str, name: str):
    """Saves device info to local JSON file."""
    path = get_config_path()
    with open(path, "w") as f:
        json.dump({"address": address, "name": name}, f)
    print(f"Saved device config for {name} ({address}) at {path}")


async def scan_and_select_device():
    """
    Scans for BLE devices (10s each pass) in a loop, letting the user re-scan if desired.
    Returns (address, name) or None if canceled.
    """
    while True:
        print("\nScanning for BLE devices (10s)...")
        devices = await BleakScanner.discover(timeout=10.0)

        if not devices:
            print("No BLE devices found.")
            again = input("Scan again? (y/n) ").strip().lower()
            if again == "y":
                continue  # re-run the scan
            else:
                return None, None

        # If we found some devices, list them:
        indexed_devices = {}
        print("\nAvailable BLE Devices:")
        for idx, d in enumerate(devices):
            dev_name = d.name or "Unknown"
            print(f"[{idx}] {dev_name} ({d.address})")
            indexed_devices[idx] = (d.address, dev_name)

        # Let user pick an index, or 'r' to re-scan
        choice = (
            input("\nEnter the number of the device to use, or 'r' to rescan: ")
            .strip()
            .lower()
        )
        if choice == "r":
            continue  # re-scan immediately

        try:
            choice_idx = int(choice)
            address, name = indexed_devices[choice_idx]
            return address, name
        except (ValueError, KeyError):
            print("Invalid selection. No device saved.")
            again = input("Scan again? (y/n) ").strip().lower()
            if again == "y":
                continue
            else:
                return None, None
