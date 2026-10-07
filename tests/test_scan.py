"""Behavior of the bundled scan program, simulated with fake pybricks modules."""

import pytest
from hubsim import MOTOR_MODES, Device, Sim

from pybricks_investigate import program

SCAN = program.scan_program()
LARGE_ANGULAR = Device(49, MOTOR_MODES, {2: (90,)})
COLOR_SENSOR = Device(61, (("COLOR", 1, 0), ("REFLT", 1, 0)), {0: (5,)})
TRAIN_MOTOR = Device(2)


def scan(until_ms=1000, flags=None, **world):
    source = program.set_flags(SCAN.read_text(), flags or {})
    return Sim(**world).run(SCAN, until_ms, source=source).output


def test_reports_hub_and_ports():
    output = scan(ports={"A": LARGE_ANGULAR, "C": COLOR_SENSOR, "D": TRAIN_MOTOR})
    assert output[:5] == [
        "hub: technichub firmware 3.6.1",
        "build: v3.6.1 on sim",
        "name: Sim Hub",
        "battery: 7600 mV 120 mA",
        "imu: up Side.TOP pitch 1 roll -2",
    ]
    assert "port A: SPIKE Large Angular Motor (id 49)" in output
    assert "  mode 2 : POS - 1 value(s), type 2" in output
    assert "port B: empty" in output
    assert "port C: SPIKE Color Sensor (id 61)" in output
    assert "port D: Powered Up Train Motor (id 2, passive)" in output
    assert output[-1] == "scan done"


def test_unknown_device_id_is_reported_raw():
    assert "port A: unknown device (id 200)" in scan(ports={"A": Device(200, (("X", 1, 0),))})


def test_firmware_3_hub_name_fallback():
    assert "name: Sim Hub (3.x)" in scan(system_info=False)


def test_remote_scan():
    assert "remote: connected, name Handset address 90:84:2B:00:00:01" in scan(
        flags={"REMOTE": True}, remote=("Handset", "90:84:2B:00:00:01")
    )
    assert "remote: none found" in scan(flags={"REMOTE": True}, until_ms=10000)


def test_watch_reports_value_changes_and_plugging():
    motor = Device(49, MOTOR_MODES, {2: [(0, (0,)), (500, (45,)), (900, (45,)), (1000, (90,))]})
    light = Device(8)
    output = scan(
        flags={"WATCH": True},
        until_ms=6000,
        ports={
            "A": motor,
            "B": [(0, None), (1500, COLOR_SENSOR)],
            "C": [(0, light), (3000, None)],
            "D": [(0, LARGE_ANGULAR), (1200, None)],
        },
    )
    assert "scan done" not in output  # watching until stopped
    watched = output[output.index("watching ports; stop with the hub button or Ctrl-C on the PC") + 1 :]
    assert [line for line in watched if line.startswith("port A")] == [
        "port A mode 2: 0",
        "port A mode 2: 45",
        "port A mode 2: 90",
    ]
    assert "port D: disconnected" in watched
    connected = watched.index("port B: connected")
    assert watched[connected + 1] == "port B: SPIKE Color Sensor (id 61)"
    assert "port B mode 0: 5" in watched
    assert "port C: disconnected" in watched  # passive: found by re-probing


def test_sim_rejects_submodule_as_attribute_like_the_firmware():
    with pytest.raises(ImportError):
        Sim().run(SCAN, 100, source="from pybricks import hubs\n")
