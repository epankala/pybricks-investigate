"""Reports the hub and every device on its ports; optionally a remote, and live changes."""

import pybricks
from pybricks.iodevices import PUPDevice
from pybricks.parameters import Port
from pybricks.tools import StopWatch, wait

# Switched on by the PC tool (`scan --watch`, `scan --remote`).
WATCH = False
REMOTE = False

WATCH_INTERVAL_MS = 200
# Empty ports and passive devices can only be checked by re-opening the port.
PROBE_INTERVAL_MS = 2000
REMOTE_TIMEOUT_MS = 5000
PORT_LETTERS = "ABCDEF"

HUB_CLASSES = {
    "movehub": "MoveHub",
    "cityhub": "CityHub",
    "technichub": "TechnicHub",
    "primehub": "PrimeHub",
    "essentialhub": "EssentialHub",
}

# LEGO device type ids as reported by PUPDevice.info()["id"].
DEVICE_NAMES = {
    1: "Powered Up Medium Motor (no encoder)",
    2: "Powered Up Train Motor",
    8: "Powered Up Light",
    34: "WeDo 2.0 Tilt Sensor",
    35: "WeDo 2.0 Motion Sensor",
    37: "BOOST Color and Distance Sensor",
    38: "BOOST Interactive Motor",
    46: "Technic Large Motor",
    47: "Technic XL Motor",
    48: "SPIKE Medium Angular Motor",
    49: "SPIKE Large Angular Motor",
    61: "SPIKE Color Sensor",
    62: "SPIKE Ultrasonic Sensor",
    63: "SPIKE Force Sensor",
    64: "SPIKE 3x3 Color Light Matrix",
    65: "SPIKE Small Angular Motor",
    75: "Technic Medium Angular Motor (grey)",
    76: "Technic Large Angular Motor (grey)",
}
# Mode watched for live values: motor position if the device has one, else mode 0.
POSITION_MODES = ("POS", "APOS")


def open_hub():
    name = HUB_CLASSES.get(pybricks.version[0])
    try:
        # `from pybricks import hubs` fails on the hub: firmware submodules are not attributes
        # of `pybricks`. A non-empty fromlist makes __import__ return the submodule itself.
        hubs = __import__("pybricks.hubs", None, None, ["hubs"])
        return getattr(hubs, name)()
    except Exception as e:
        print("hub: cannot open hub class", name, e)
        return None


def hub_name(hub):
    try:
        return hub.system.info()["name"]  # firmware 4.x
    except Exception:
        pass
    try:
        return hub.system.name()  # firmware 3.x
    except Exception:
        return None


def report_hub(hub):
    print("hub:", pybricks.version[0], "firmware", pybricks.version[1])
    print("build:", pybricks.version[2])
    if hub is None:
        return
    name = hub_name(hub)
    if name:
        print("name:", name)
    print("battery:", hub.battery.voltage(), "mV", hub.battery.current(), "mA")
    imu = getattr(hub, "imu", None)
    if imu:
        pitch, roll = imu.tilt()
        print("imu: up", imu.up(), "pitch", pitch, "roll", roll)


def ports():
    for letter in PORT_LETTERS:
        port = getattr(Port, letter, None)
        if port is not None:
            yield letter, port


def open_device(port):
    """PUPDevice on the port, None if empty; raises ValueError if the hub lacks the port."""
    try:
        return PUPDevice(port)
    except OSError:
        return None


def watch_mode(modes):
    for index, mode in enumerate(modes):
        if mode[0] in POSITION_MODES:
            return index
    return 0 if modes else None


def describe(letter, device):
    """Print the device and return the mode to watch (None for passive devices)."""
    info = device.info()
    device_id = info["id"]
    modes = info.get("modes", ())
    kind = "" if modes else ", passive"
    print("port " + letter + ":", DEVICE_NAMES.get(device_id, "unknown device"), "(id " + str(device_id) + kind + ")")
    for index, mode in enumerate(modes):
        print("  mode", index, ":", mode[0], "-", mode[1], "value(s), type", mode[2])
    return watch_mode(modes)


def scan_ports():
    """Print every port; returns {letter: (port, device or None, watched mode)}."""
    found = {}
    for letter, port in ports():
        try:
            device = open_device(port)
        except ValueError:
            continue  # this hub has no such port
        if device is None:
            print("port " + letter + ": empty")
            found[letter] = (port, None, None)
        else:
            found[letter] = (port, device, describe(letter, device))
    return found


def scan_remote():
    from pybricks.pupdevices import Remote

    print("remote: searching for", REMOTE_TIMEOUT_MS // 1000, "s, switch it on")
    try:
        remote = Remote(timeout=REMOTE_TIMEOUT_MS)
    except OSError:
        print("remote: none found")
        return
    try:
        name = remote.name()
    except Exception:
        name = "?"
    print("remote: connected,", "name", name, "address", getattr(remote, "address", "?"))


def format_values(values):
    return " ".join(str(v) for v in values)


def watch(found):
    print("watching ports; stop with the hub button or Ctrl-C on the PC")
    last = {}
    probe = StopWatch()
    while True:
        for letter, (port, device, mode) in list(found.items()):
            if device is None or mode is None:
                continue
            try:
                values = device.read(mode)
            except OSError:
                print("port " + letter + ": disconnected")
                found[letter] = (port, None, None)
                last.pop(letter, None)
                continue
            if values != last.get(letter):
                last[letter] = values
                print("port " + letter + " mode " + str(mode) + ":", format_values(values))

        if probe.time() >= PROBE_INTERVAL_MS:
            probe.reset()
            for letter, (port, device, mode) in list(found.items()):
                if device is not None and mode is not None:
                    continue  # readable devices are checked by read()
                current = open_device(port)
                if current is None and device is not None:
                    print("port " + letter + ": disconnected")
                    found[letter] = (port, None, None)
                elif current is not None and device is None:
                    print("port " + letter + ": connected")
                    found[letter] = (port, current, describe(letter, current))

        wait(WATCH_INTERVAL_MS)


def main():
    report_hub(open_hub())
    found = scan_ports()
    if REMOTE:
        scan_remote()
    if WATCH:
        watch(found)
    print("scan done")


main()
