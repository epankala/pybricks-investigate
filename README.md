# pybricks-investigate

Tools for finding out what is going on with a [Pybricks](https://pybricks.com) hub:

- **scan** the hub and the devices plugged into its ports (optionally a Powered Up remote,
  and live plug/unplug and sensor/motor value changes), and
- **run** any hub program and print whatever it prints on the PC console.

## Setup and use

```sh
make install     # .venv + editable install of the tool with dev tools
make scan        # hub type, firmware, name, battery, IMU and every port's device
make watch       # scan, then keep reporting changes until Ctrl-C
make run         # run hub/example.py and print its output
make run PROGRAM=hub/mine.py ARGS="--debug -t"   # your program, DEBUG on, timestamped
make stop        # stop the program running on the hub
make compile     # compile PROGRAM locally into build/<name>.bin (no hub needed)
make check       # ruff + pytest (incl. simulated scan program) + compile
```

`HUB="Pybricks Hub"` picks a hub by name, `ARGS="..."` passes tool options. Without make:
`pip install -e .` and `pybricks-investigate --help`, e.g. `pybricks-investigate scan --remote`.

Hub output goes to stdout and the tool's log to stderr, so `make scan > scan.txt` captures
only what the hub printed. Uploads are retried (`--attempts`, default 3) since BLE links
occasionally drop mid-upload, and a program already running on the hub is stopped first.

Programs are uploaded in 120-byte chunks (`--chunk-size`). pybricksdev otherwise uses the
largest chunk the hub allows: 150 bytes on a Technic Hub, filling its BLE MTU of 158. On
firmware 4.0.1 such writes were acknowledged by the hub's radio but sometimes never
answered, so every upload larger than 2400 bytes stalled; 140-byte and smaller chunks worked.
Ctrl-C stops the hub program; a program that ends by itself is left alone.

## Scan output

```
hub: technichub firmware 3.6.1
build: v3.6.1 on ...
name: Pybricks Hub
battery: 7650 mV 120 mA
imu: up Side.TOP pitch 0 roll 1
port A: SPIKE Large Angular Motor (id 49)
  mode 0 : POWER - 1 value(s), type 0
  ...
port B: empty
port D: Powered Up Train Motor (id 2, passive)
scan done
```

Devices are named from their LEGO type id (unknown ids are printed raw); UART devices also
list their modes (name, number of values, data type). Passive devices (DC motors, lights)
only report their id. `--remote` (`-r`) also looks for a Powered Up remote for 5 s.

`--watch` (`make watch`) keeps running and prints a line whenever a watched value changes:
the position mode (`POS`) for motors, mode 0 for sensors. Unplugging and plugging devices
is reported too; for empty ports and passive devices this is checked every 2 s.

The scan program (`src/pybricks_investigate/hub/scan.py`) works on any Pybricks hub: it
picks the hub class from `pybricks.version` and tries ports A-F. The hub name comes from
`hub.system.info()` on firmware 4.x and `hub.system.name()` on 3.x.

## Running your own programs

`run` uploads any hub program and prints its output until it ends. Local imports work:
pybricksdev compiles imported modules from the program's directory into the same upload.
With `--debug`, a program's `DEBUG = False` line is switched on in a temporary copy.
`-t` prefixes each line with the PC time.

`tests/hubsim.py` runs a hub program under CPython against fake `pybricks` modules with a
simulated clock; see `tests/test_scan.py`.
