import asyncio
import csv
import queue
import threading
import time
from datetime import datetime

from bleak import BleakClient

from .config import load_device_config, save_device_config, scan_and_select_device

# Standard UUID for Heart Rate Measurement characteristic
HR_MEASUREMENT_UUID = "00002a37-0000-1000-8000-00805f9b34fb"


class recorder:
    def __init__(self):
        self._address: str | None = None
        self._device_name = None

        self._ble_client = None
        self._thread = None
        self._run_flag = threading.Event()  # used to keep background loop running
        self._connected = False

        # Shared data structures
        self._data_queue = queue.Queue()  # Holds (timestamp, HR, list_of_RR_intervals)
        self._current_hr = 0
        self._rr_buffer = []  # For HRV calculations
        self._rr_buffer_times = []

        # Recording state
        self._recording = False
        self._pause_flag = False
        self._csv_file = None
        self._csv_writer = None
        self._record_start_time = None
        self._filename = None

    # --------------------------------------------------------------------------
    # 1) Config
    # --------------------------------------------------------------------------
    def config(self):
        """
        Load or create config. If a config file already exists, prompt to keep or replace.
        If none exists, do repeated scanning to choose a device.
        """
        existing = load_device_config()
        if existing:
            current_name = existing["name"]
            current_addr = existing["address"]
            choice = (
                input(
                    f"A config for device '{current_name}' ({current_addr}) already exists.\n"
                    "Do you want to keep it (k) or replace it (r)? "
                )
                .strip()
                .lower()
            )

            if choice == "k":
                # Keep current config
                self._address = current_addr
                self._device_name = current_name
                print(f"Loaded device config: {self._device_name} ({self._address})")
                return
            elif choice == "r":
                # Overwrite existing config with new scan
                print("Replacing existing config. Scanning for devices...")
                address, name = asyncio.run(scan_and_select_device())
                if address and name:
                    save_device_config(address, name)
                    self._address = address
                    self._device_name = name
                else:
                    print("No device selected. Config not replaced.")
                return
            else:
                print("Invalid choice. Keeping existing config.")
                self._address = current_addr
                self._device_name = current_name
                print(f"Loaded device config: {self._device_name} ({self._address})")
                return
        else:
            # No existing config found, do a scan
            address, name = asyncio.run(scan_and_select_device())
            if address and name:
                save_device_config(address, name)
                self._address = address
                self._device_name = name
            else:
                print("No device selected. Config file not created.")

    # --------------------------------------------------------------------------
    # 2) Start
    # --------------------------------------------------------------------------
    def start(self, timeout=10.0):
        """
        If we don't have an address in memory, load from config or run config() if none found.
        Then spin up the background thread that connects & listens.
        """
        if not self._address:
            # 1) Load or do config logic if needed
            existing = load_device_config()
            if existing:
                # Found an existing config
                self._address = existing["address"]
                self._device_name = existing["name"]
                print(f"Loaded device config: {self._device_name} ({self._address})")
            else:
                # No file => run the normal config logic (which might prompt scanning, etc.)
                print("No config file found. Running config() now.")
                self.config()  # will set self._address if successful
            # If we still have no address, bail out
            if not self._address:
                print("No device configured. Aborting start().")
                return

        # 2) If already started, do nothing
        if self._thread and self._thread.is_alive():
            print("Already started.")
            return

        # 3) Spin up the background thread that handles async connection
        self._run_flag.set()
        self._thread = threading.Thread(target=self._background_main, daemon=True)
        self._thread.start()

        # 4) Block the main thread until 'self._connected' is True or timeout
        start_time = time.time()
        while not self._connected and (time.time() - start_time < timeout):
            time.sleep(0.1)  # short sleep, then check again

        if self._connected:
            print("Device connected.")
        else:
            print(f"Could not connect within {timeout} seconds.")

        print("Background BLE listener thread started.")

    # --------------------------------------------------------------------------
    # 3) get(interval=0)
    # --------------------------------------------------------------------------
    def get(self, interval=0):
        if not self._connected:
            return "Not connected."

        if interval <= 0:
            return f"HR: {self._current_hr}, HRV: {self._compute_hrv():.2f}"
        else:
            cutoff = time.time() - interval
            relevant_rrs = [
                r
                for (r, t) in zip(self._rr_buffer, self._rr_buffer_times)
                if t >= cutoff
            ]
            if not relevant_rrs:
                return "No data in the interval."

            # Average HR = 60 / average RR (in seconds), RR in ms -> convert to s
            avg_rr_s = sum(relevant_rrs) / len(relevant_rrs) / 1000.0
            avg_hr = 60.0 / avg_rr_s if avg_rr_s else 0.0

            # Compute naive RMSSD
            r_peaks = [r / 1000.0 for r in relevant_rrs]
            diffs = []
            for i in range(len(r_peaks) - 1):
                diffs.append((r_peaks[i + 1] - r_peaks[i]) ** 2)
            if diffs:
                rmssd = (sum(diffs) / len(diffs)) ** 0.5
            else:
                rmssd = 0.0

            return f"Avg HR: {avg_hr:.1f}, HRV(RMSSD): {rmssd:.2f}"

    # --------------------------------------------------------------------------
    # 4) record()
    # --------------------------------------------------------------------------
    def record(self):
        if not self._connected:
            print("Not connected to device. Attempting to start now...")
            self.start()

        if not self._connected:
            print("Unable to connect, aborting record().")
            return

        if self._recording:
            print("Already recording.")
            return

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._filename = f"hrm_record_{timestamp_str}.csv"
        self._csv_file = open(self._filename, "w", newline="")
        self._csv_writer = csv.writer(self._csv_file)
        self._csv_writer.writerow(["timestamp", "hr", "hrv_rmssd_30s", "event"])

        self._record_start_time = datetime.now()
        self._recording = True
        self._pause_flag = False

        # Log "start" event
        self._csv_writer.writerow([datetime.now().isoformat(), "", "", "record_start"])
        print(f"Recording to {self._filename}...")

    # --------------------------------------------------------------------------
    # 5) pause()
    # --------------------------------------------------------------------------
    def pause(self):
        if self._recording and not self._pause_flag:
            self._pause_flag = True
            if self._csv_writer:
                self._csv_writer.writerow(
                    [datetime.now().isoformat(), "", "", "paused"]
                )
            print("Recording paused.")

    # --------------------------------------------------------------------------
    # 6) resume()
    # --------------------------------------------------------------------------
    def resume(self):
        if self._recording and self._pause_flag:
            self._pause_flag = False
            if self._csv_writer:
                self._csv_writer.writerow(
                    [datetime.now().isoformat(), "", "", "resumed"]
                )
            print("Recording resumed.")

    # --------------------------------------------------------------------------
    # 7) stop()
    # --------------------------------------------------------------------------
    def stop(self):
        """Stops recording but does NOT kill the background thread.
        The background BLE read is still ongoing until exit()."""
        if self._recording:
            if self._csv_writer:
                self._csv_writer.writerow(
                    [datetime.now().isoformat(), "", "", "record_stop"]
                )
            self._recording = False
            self._pause_flag = False
            if self._csv_file:
                self._csv_file.close()
                self._csv_file = None
            self._csv_writer = None
            print(f"Recording stopped. CSV saved to {self._filename}")

    # --------------------------------------------------------------------------
    # 8) exit()
    # --------------------------------------------------------------------------
    def exit(self):
        """Stop recording if needed, then signal the background thread to close."""
        self.stop()
        self._run_flag.clear()  # background loop sees this and breaks
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        print("Exited BLE listener. Goodbye.")

    # --------------------------------------------------------------------------
    # "Main" function for the background thread
    # --------------------------------------------------------------------------
    def _background_main(self):
        """Runs an asyncio event loop in this thread using asyncio.run()."""
        try:
            asyncio.run(self._run_ble_client())
        except Exception as e:
            print(f"[Background] Exception in _background_main: {e}")
        finally:
            self._connected = False
            print("[Background] Done with event loop.")

    # --------------------------------------------------------------------------
    # The main async routine that handles BLE connection & notifications
    # --------------------------------------------------------------------------
    async def _run_ble_client(self):
        """Async code run inside the background thread's event loop."""
        try:
            if self._address is None:
                raise ValueError("No address configured.")

            print("DEBUG: Creating BleakClient and connecting...")
            self._ble_client = BleakClient(self._address)
            await self._ble_client.connect()
            self._connected = self._ble_client.is_connected
            if not self._connected:
                print("Failed to connect to BLE device.")
                return
            print(f"Connected to BLE device: {self._device_name} ({self._address})")

            await self._ble_client.start_notify(
                HR_MEASUREMENT_UUID, self._notification_handler
            )

            # Keep looping while run_flag is set
            while self._run_flag.is_set():
                await asyncio.sleep(0.1)

            # Stopping notify & disconnecting
            await self._ble_client.stop_notify(HR_MEASUREMENT_UUID)
            await self._ble_client.disconnect()
        except Exception as e:
            print(f"Error in BLE client loop: {e}")
        finally:
            self._ble_client = None
            self._connected = False
            print("DEBUG: _run_ble_client EXITING")

    # --------------------------------------------------------------------------
    # Notification Handler
    # --------------------------------------------------------------------------
    def _notification_handler(self, sender, data: bytearray):
        flags = data[0]
        hr_format = flags & 0x01
        rr_present = (flags >> 4) & 0x01

        offset = 1
        if hr_format == 0:
            hr_value = data[offset]
            offset += 1
        else:
            hr_value = int.from_bytes(data[offset : offset + 2], byteorder="little")
            offset += 2

        self._current_hr = hr_value

        rr_intervals = []
        if rr_present:
            while (offset + 1) < len(data):
                rr = int.from_bytes(data[offset : offset + 2], byteorder="little")
                rr_intervals.append(rr)
                offset += 2

        now = time.time()
        for rr in rr_intervals:
            self._rr_buffer.append(rr)
            self._rr_buffer_times.append(now)
            # keep only last 30s
            cutoff = now - 30
            while self._rr_buffer_times and self._rr_buffer_times[0] < cutoff:
                self._rr_buffer_times.pop(0)
                self._rr_buffer.pop(0)

        # If recording, write to CSV
        if self._recording and not self._pause_flag:
            hrv = self._compute_hrv()
            timestamp_iso = datetime.now().isoformat()
            if self._csv_writer:
                self._csv_writer.writerow([timestamp_iso, hr_value, f"{hrv:.2f}", ""])
                self._csv_file.flush()

    def _compute_hrv(self):
        if len(self._rr_buffer) < 2:
            return 0.0
        rr_s = [r / 1000.0 for r in self._rr_buffer]
        diffs_sq = []
        for i in range(len(rr_s) - 1):
            diff = (rr_s[i + 1] - rr_s[i]) ** 2
            diffs_sq.append(diff)
        if not diffs_sq:
            return 0.0
        mean_diff_sq = sum(diffs_sq) / len(diffs_sq)
        return mean_diff_sq**0.5
