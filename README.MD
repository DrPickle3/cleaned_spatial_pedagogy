# Spatial Pedagogy

## Requirements

### Python Dependencies

Install the required Python packages:

```bash
pip install -r requirements.txt
```

### Hardware Requirements

- ESP32 with DW1000 UWB module (Makerfabs ESP32 UWB)
- At least 2-3 anchors for positioning (3+ recommended for accuracy)
- 1 tag device

## To push new code on the hardware

### To build the executable (look for errors)
```bash
pio run
```

### To upload it in the esp32
```bash
pio run --target upload
```

### To monitor the prints of the device (has to be plugged in the computer)
```bash
pio device monitor
```

---

## Python Scripts

All Python scripts are located in the `scripts/` directory.

To go in the directory :
```bash
cd scripts
```

To go back a folder :
```bash
cd ..
```
### 1. Server (`server.py`)

Receives UWB data from the Tag via TCP, computes positions using trilateration, and writes results to a CSV file.

```bash
cd scripts
python server.py
```

**Options:**
| Flag | Description |
|------|-------------|
| `--display` | Show real-time turtle graphics visualization |

**Example with display:**
```bash
python server.py --display
```

**Note:** Requires a `config.json` file in the parent directory with anchor positions. The server uses mDNS (Zeroconf) for discovery on port 5000. The computer has to be connected to the same mobile hotspot the Tag is trying to connect. You will need a secrets.h file in src/ containing :

```cpp
#pragma once

const char* WIFI_PASS = "spatial123";
const char* WIFI_NAME = "Spatial_Pedagogy";
```
Change those credentials to whatever your hotspot is.

---

### 2. Visualizer (`visualizer.py`)

Displays trajectory visualization from recorded CSV data with various analysis options.

```bash
cd scripts
python visualizer.py
```

**Options:**
| Flag | Description |
|------|-------------|
| `--csv <path>` | Path to CSV file (default: `../logs/positions.csv`) |
| `--heatmap` | Display heatmap of position density |
| `--stops` | Detect and display stops in the trajectory |
| `--precision` | Show precision statistics (for stationary measurements) |
| `--trail <n>` | Number of past positions to show (default: 10) |
| `--max_time_diff <s>` | Max time between positions in seconds (default: 0.2) |
| `--calibration` | Run image calibration for overlay visualization |
| `--experiment <path>` | Use pre-calibrated experiment folder |

**Examples:**
```bash
# Basic visualization
python visualizer.py --csv ../logs/positions.csv

# With heatmap and stop detection
python visualizer.py --csv ../logs/positions.csv --heatmap --stops

# Precision analysis for stationary tag
python visualizer.py --csv ../logs/stationary_positions.csv --precision

# With image calibration
python visualizer.py --csv ../logs/positions.csv --calibration
```

---

### 3. Mean Range Calculator (`meanRange.py`)

Calculates and displays the mean measured range for each anchor from a CSV file.

```bash
cd scripts
python meanRange.py
```

**Options:**
| Flag | Description |
|------|-------------|
| `--csv <path>` | Path to CSV file (default: `../logs/positions.csv`) |

**Example:**
```bash
python meanRange.py --csv ../logs/positions.csv
```

---

### 4. Antenna Delay Calibration - Triangle Method (`antDelayTriangle.py`)

Computes antenna delay corrections for 3 devices (1 tag + 2 anchors) using triangle measurements.

```bash
cd scripts
python antDelayTriangle.py
```

**Before running:** Edit the script to set your measured and true distances:
```python
true_distances = {
    ('Tag', 'Anchor1'): 3.6068,  # meters
    ('Tag', 'Anchor4'): 3.8608,
    ('Anchor1', 'Anchor4'): 2.5400
}

measured_distances = {
    ('Tag', 'Anchor1'): 4.092,
    ('Tag', 'Anchor4'): 4.262,
    ('Anchor1', 'Anchor4'): 2.664
}
```

---

### 5. Antenna Delay Calibration - Single Line Method (`antDelaySingleLine.py`)

Computes antenna delay for a single anchor using one known distance.

```bash
cd scripts
python antDelaySingleLine.py
```

**Before running:** Edit the script with your measurements:
```python
true_distance = 3.37      # real distance in meters
measured_distance = 3.181 # measured distance
```

---

## Configuration Files

### `config.json`

Main configuration file with anchor positions (x, y, z in meters):

```json
{
  "anchors": {
    "AAA1": [6.8834, 0.635, 0.0],
    "AAA2": [10.9982, 4.9784, 0.0],
    "AAA3": [10.9982, 0.0, 0.0]
  }
}
```

Alternative configs available:
- `config_boisjoli.json`
- `config_brin_univers.json`
- `config_square.json`

---

## Code modifications I had to do to make the devices work

In the DW1000 original library, it does not support having a 5th anchor connected to a tag.
We have to manually change the library code to adapt it to our case. We need to modify 2 different files :

### DW1000/src/DW1000.cpp
At the line 172, there is this line

```cpp
#ifndef ESP8266
```

I changed it to (to support esp32)

```cpp
#ifdef ESP8266
```

### DW1000/src/DW1000Ranging.cpp

Added a check if we can add the new device in the array before doing it. (line 243)

```cpp
if(_networkDevicesNumber + 1 <= MAX_DEVICES && addDevice)
```

---

## Typical Workflow

1. **Setup anchors** - Place anchors and measure their positions
2. **Configure** - Update `config.json` with anchor coordinates
3. **Start server** - Run `python server.py`
4. **Collect data** - Move the tag around
5. **Visualize** - Use `python visualizer.py` to analyze results

## Workflow for new devices

1. **Calibrate antennas** - Use `antDelayTriangle.py` or `antDelaySingleLine.py`
2. **Flash devices** - Use `pio run --target upload` while the anchor/tag is plugged in a USB port

## Phone details

### PIN
1545

## TODO

### Network socket timeout

When I did my precision 1d, the server goes timeout because it doesn't receive anything from the Tag but
it's because there are no anchors not because we lost connection to the Tag. We probably want to investigate this further... For now I just put the timeout to 800 seconds instead of 8 seconds.