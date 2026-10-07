"""hub/example.py reading the devices from the user's scan, simulated with fake pybricks modules."""

from pathlib import Path

from hubsim import MOTOR_MODES, Device, Sim

from pybricks_investigate import program

EXAMPLE = Path(__file__).parent.parent / "hub" / "example.py"
CDS_MODES = (("COLOR", 1, 0), ("PROX", 1, 0), ("COUNT", 1, 2), ("REFLT", 1, 0), ("AMBI", 1, 0))
SPIKE_MODES = (("COLOR", 1, 0), ("REFLT", 1, 0), ("AMBI", 1, 0))


def boost_motor():
    return Device(38, MOTOR_MODES, {1: (0,), 2: (90,)})


def color_distance():
    return Device(37, CDS_MODES, {0: ("Color.RED",), 1: (40,), 3: (12,), 4: (3,)})


def spike_color():
    return Device(61, SPIKE_MODES, {0: ("Color.BLUE",), 1: (55,), 2: (7,)})


def readings(output):
    return [line for line in output if "skipped" not in line]


def run(ports, until_ms=1200, debug=False):
    source = EXAMPLE.read_text()
    if debug:
        source = program.set_flags(source, {"DEBUG": True})
    return Sim(ports=ports).run(EXAMPLE, until_ms, source=source).output


def test_reads_motor_and_both_sensors():
    output = run({"A": boost_motor(), "C": color_distance(), "D": spike_color()})
    assert output[0] == "A angle 90 deg speed 0 deg/s | C Color.RED dist 40% | D Color.BLUE"
    assert len(output) == 3  # one line every 500 ms


def test_values_follow_the_devices():
    motor = Device(38, MOTOR_MODES, {1: [(0, (0,)), (600, (120,))], 2: [(0, (0,)), (600, (45,))]})
    assert readings(run({"A": motor})) == [
        "A angle 0 deg speed 0 deg/s",
        "A angle 0 deg speed 0 deg/s",
        "A angle 45 deg speed 120 deg/s",
    ]


def test_debug_adds_reflection_ambient_and_hsv():
    line = readings(run({"C": color_distance(), "D": spike_color()}, debug=True))[0]
    assert line == (
        "C Color.RED dist 40% refl 12% amb 3% Color(h=0, s=0, v=12)"
        " | D Color.BLUE refl 55% amb 7% Color(h=240, s=100, v=55)"
    )


def test_missing_or_wrong_devices_are_skipped():
    output = run({"A": spike_color(), "D": spike_color()})  # color sensor on the motor port
    assert output[:2] == [
        "port A skipped: device missing or of another type",
        "port C skipped: device missing or of another type",
    ]
    assert output[2] == "D Color.BLUE"


def test_nothing_connected():
    output = run({})
    assert output[3:] == ["no devices to read"] * 3


def test_unplugged_sensor_is_dropped_and_others_keep_reading():
    output = run({"A": boost_motor(), "C": [(0, color_distance()), (700, None)]}, until_ms=1700)
    assert readings(output) == [
        "A angle 90 deg speed 0 deg/s | C Color.RED dist 40%",
        "A angle 90 deg speed 0 deg/s | C Color.RED dist 40%",
        "port C disconnected",
        "A angle 90 deg speed 0 deg/s",
        "A angle 90 deg speed 0 deg/s",
    ]
