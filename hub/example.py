"""Example for `make run`: everything this program prints appears on the PC console."""

from pybricks.hubs import TechnicHub
from pybricks.tools import StopWatch, wait

# `make run ARGS=--debug` switches this on.
DEBUG = False

hub = TechnicHub()
clock = StopWatch()

print("hello from the hub")
for tick in range(10):
    print("tick", tick, "at", clock.time(), "ms, battery", hub.battery.voltage(), "mV")
    if DEBUG:
        print("  current", hub.battery.current(), "mA")
    wait(1000)
print("done")
