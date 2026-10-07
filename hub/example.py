"""Example for `make run`: reads the devices found by `make scan` and prints their values.

Port A: motor angle and speed (only read, never driven: turn it by hand).
Port C: Color and Distance Sensor color and distance. Port D: SPIKE Color Sensor color.
Runs until stopped with Ctrl-C on the PC or the hub button; missing devices are skipped.
"""

from pybricks.parameters import Port
from pybricks.pupdevices import ColorDistanceSensor, ColorSensor, Motor
from pybricks.tools import wait

# `make run ARGS=--debug` switches this on: also reflection, ambient light and HSV.
DEBUG = False
INTERVAL_MS = 500


def details(sensor):
    return " refl %d%% amb %d%% %s" % (sensor.reflection(), sensor.ambient(), sensor.hsv()) if DEBUG else ""


def read_motor(motor):
    return "angle %d deg speed %d deg/s" % (motor.angle(), motor.speed())


def read_distance_sensor(sensor):
    return "%s dist %d%%%s" % (sensor.color(), sensor.distance(), details(sensor))


def read_color_sensor(sensor):
    return "%s%s" % (sensor.color(), details(sensor))


# (port label, device class, port, reader)
DEVICES = [
    ("A", Motor, Port.A, read_motor),
    ("C", ColorDistanceSensor, Port.C, read_distance_sensor),
    ("D", ColorSensor, Port.D, read_color_sensor),
]

devices = []
for label, kind, port, reader in DEVICES:
    try:
        devices.append((label, kind(port), reader))
    except OSError:
        print("port", label, "skipped: device missing or of another type")

while True:
    parts = []
    for entry in list(devices):
        label, device, reader = entry
        try:
            parts.append(label + " " + reader(device))
        except OSError:
            print("port", label, "disconnected")
            devices.remove(entry)
    print(" | ".join(parts) if parts else "no devices to read")
    wait(INTERVAL_MS)
