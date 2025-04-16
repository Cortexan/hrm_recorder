# hrm-recorder
**hrm-recorder** is a Python library for interacting with Bluetooth LE heart rate monitors. It lets you scan for devices, save configuration, connect to a chosen device, and record real-time heart rate data (and basic HRV-like data) in CSV files.

## Features
- **One-Time Config** – A quick CLI command `hrm-recorder config` to discover BLE heart rate devices and store their addresses locally.  
- **Recorder Class** – A Python class (`recorder`) for starting a BLE connection in the background, retrieving data, and optionally logging to CSV.  
- **Pause/Resume** – Pause the data logging without disconnecting.  
- **Simple API** – Use it in IPython, a standard Python script, or any environment that keeps the session alive.

## Installation
Install from PyPI with:
```bash
pip install hrm-recorder
```

Or install from source:
```bash
git clone https://github.com/Cortexan/hrm_recorder.git
cd hrm-recorder
pip install .
```

> **Note**: `hrm-recorder` requires Python 3.9+ and the [bleak](https://github.com/hbldh/bleak) library for BLE functionality on Windows, macOS, and Linux.

## Basic Usage

### 1) Run Config from the CLI

```bash
hrm-recorder config
```
1. Scans for nearby BLE devices (10s each scan).  
2. Lets you pick the device to save in \`.hrm_config.json\`.  
3. If a config file already exists, it’ll ask if you want to keep or replace it.  


### 2) Usage in a Python Script or REPL

Create and use a `recorder` instance:

```python
from hrm_recorder import recorder

# Create a new recorder instance
hrm = recorder()

# Optionally re-run config if you want to change the saved device
hrm.config()

# Start the background BLE thread
hrm.start()

# Get a quick HR reading
print(hrm.get())  # e.g. "HR: 72, HRV: 32.00"

# Start recording data to a CSV file
hrm.record()
# ... some time later ...
hrm.stop()

# Eventually exit (stop the background thread)
hrm.exit()
```
## Contributing
1. **Fork** the repo
2. **Create** a feature branch
3. **Commit** your changes
4. **Open** a Pull Request

We’re happy to see improvements for advanced HRV, multi-device support, etc.

## License
This project is licensed under the MIT License. See [LICENSE](LICENSE.txt) for details.