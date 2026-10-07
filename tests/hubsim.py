"""Runs a hub program under CPython against fake ``pybricks`` modules and a simulated clock."""

import sys
import types
from pathlib import Path

MODULES = (
    "pybricks",
    "pybricks.hubs",
    "pybricks.iodevices",
    "pybricks.parameters",
    "pybricks.pupdevices",
    "pybricks.tools",
)
MOTOR_MODES = (("POWER", 1, 0), ("SPEED", 1, 0), ("POS", 1, 2), ("APOS", 1, 1), ("LOAD", 1, 0))


class StopSim(Exception):
    pass


class Device:
    """A device on a port: ``modes`` empty means passive; ``values`` maps mode -> tuple or list of (t_ms, tuple)."""

    def __init__(self, device_id, modes=(), values=None):
        self.device_id = device_id
        self.modes = modes
        self.values = values or {}


class Sim:
    """``ports``: letter -> Device, or a list of ``(t_ms, Device or None)`` for plugging and unplugging."""

    def __init__(self, ports=None, hub_kind="technichub", firmware="3.6.1", remote=None, system_info=True):
        self.clock = 0
        self.ports = ports or {}
        self.hub_kind = hub_kind
        self.firmware = firmware
        self.remote = remote  # None: no remote in range, else (name, address)
        self.system_info = system_info  # firmware 4.x has system.info(), 3.x system.name()
        self.output = []

    def advance(self, ms):
        self.clock += ms
        if self.clock > self.until:
            raise StopSim

    def device_at(self, letter):
        spec = self.ports.get(letter)
        if isinstance(spec, list):
            current = None
            for t, device in spec:
                if t <= self.clock:
                    current = device
            return current
        return spec

    def run(self, path, until_ms, source=None):
        self.until = until_ms
        code = compile(source if source is not None else Path(path).read_text(), str(path), "exec")
        saved = {name: sys.modules.get(name) for name in MODULES}
        sys.modules.update(self._modules())
        try:
            exec(code, {"__name__": "__main__", "print": lambda *a: self.output.append(" ".join(map(str, a)))})
        except StopSim:
            pass
        finally:
            for name, module in saved.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module
        return self

    def _modules(self):
        sim = self

        class Port:
            A, B, C, D = "A", "B", "C", "D"  # a Technic Hub: no E/F

        class Battery:
            def voltage(self):
                return 7600

            def current(self):
                return 120

        class IMU:
            def up(self):
                return "Side.TOP"

            def tilt(self):
                return (1, -2)

        class System:
            def info(self):
                if not sim.system_info:
                    raise AttributeError("info")
                return {"name": "Sim Hub"}

            def name(self):
                return "Sim Hub (3.x)"

        class TechnicHub:
            def __init__(self):
                self.battery = Battery()
                self.imu = IMU()
                self.system = System()

        class PUPDevice:
            def __init__(self, port):
                if port not in "ABCD":
                    raise ValueError("port")
                self.port = port
                self.device = sim.device_at(port)
                if self.device is None:
                    raise OSError(19, "no device")

            def info(self):
                if not self.device.modes:
                    return {"id": self.device.device_id}
                return {"id": self.device.device_id, "modes": self.device.modes}

            def read(self, mode):
                if sim.device_at(self.port) is not self.device:
                    raise OSError(19, "disconnected")
                if not self.device.modes:
                    raise OSError(95, "passive device")
                values = self.device.values.get(mode, (0,))
                if isinstance(values, list):
                    return [v for t, v in values if t <= sim.clock][-1]
                return values

        class Remote:
            def __init__(self, name=None, timeout=10000):
                if sim.remote is None:
                    sim.advance(timeout)
                    raise OSError(110, "timed out")
                self.address = sim.remote[1]

            def name(self):
                return sim.remote[0]

        class StopWatch:
            def __init__(self):
                self.t0 = sim.clock

            def reset(self):
                self.t0 = sim.clock

            def time(self):
                return sim.clock - self.t0

        hubs = _module("pybricks.hubs", TechnicHub=TechnicHub)
        # Like the firmware, submodules are not attributes of `pybricks`, so `from pybricks import hubs`
        # fails. The odd __name__ stops CPython's fallback to sys.modules["pybricks.hubs"].
        pybricks = _module("pybricks-firmware", version=(sim.hub_kind, sim.firmware, f"v{sim.firmware} on sim"))
        return {
            "pybricks": pybricks,
            "pybricks.hubs": hubs,
            "pybricks.iodevices": _module("pybricks.iodevices", PUPDevice=PUPDevice),
            "pybricks.parameters": _module("pybricks.parameters", Port=Port),
            "pybricks.pupdevices": _module("pybricks.pupdevices", Remote=Remote),
            "pybricks.tools": _module("pybricks.tools", StopWatch=StopWatch, wait=sim.advance),
        }


def _module(name, **attrs):
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    return module
