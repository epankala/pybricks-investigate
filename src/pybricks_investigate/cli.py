"""Scan a Pybricks hub for devices and stream hub program output to the PC."""

import argparse
import asyncio
import logging
import sys
import tempfile
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

from bleak.exc import BleakError, BleakGATTProtocolError
from pybricksdev.ble import find_device
from pybricksdev.ble.pybricks import CommandError, StatusFlag
from pybricksdev.connections import ConnectionState
from pybricksdev.connections.pybricks import HubDisconnectError, PybricksHubBLE

from . import program

logger = logging.getLogger("pybricks_investigate")

CONNECT_RETRY_DELAY = 1.0
# A program left running on the hub makes uploads and starts fail with BUSY.
STOP_PROGRAM_RETRIES = 3
STOP_PROGRAM_SETTLE = 0.5
# Failures worth a fresh attempt; typically a flaky BLE link during upload.
RETRY_ERRORS = (BleakError, HubDisconnectError, TimeoutError, asyncio.TimeoutError)
# Program bytes per upload write. pybricksdev sends the largest chunk the hub allows: 150 on a
# Technic Hub, filling its BLE MTU of 158. On firmware 4.0.1 such writes were acknowledged by the
# hub's radio but sometimes never answered, stalling uploads at 2400 bytes; 140 and below worked.
DEFAULT_CHUNK_SIZE = 120
CHUNK_HEADER = 5  # command byte + 32-bit offset in front of each chunk
# If the running flag never shows up, the program ended before a status report arrived.
PROGRAM_START_TIMEOUT = 2.0
# The firmware may clear the running flag before the last output has arrived.
OUTPUT_FLUSH_DELAY = 0.5


class HubNotFound(Exception):
    pass


def limit_chunk_size(hub: PybricksHubBLE, chunk_size: int) -> None:
    # pybricksdev sizes upload chunks (and stdin writes) from this private field.
##    hub._max_write_size = min(hub._max_write_size, chunk_size + CHUNK_HEADER)
    pass


def error_text(e: BaseException) -> str:
    return str(e.args[-1]) if e.args else type(e).__name__


class ProgramWatcher:
    """Tracks one program run through the hub's status flags.

    Create it right before starting the program, so an earlier program's
    running flag is not mistaken for this one.
    """

    def __init__(self, hub: PybricksHubBLE):
        self.started = asyncio.Event()
        self.stopped = asyncio.Event()
        self._subscription = hub.status_observable.subscribe(self._on_status)

    def _on_status(self, flags: StatusFlag) -> None:
        if flags & StatusFlag.USER_PROGRAM_RUNNING:
            self.started.set()
        elif self.started.is_set():
            self.stopped.set()

    async def wait_stopped(self) -> None:
        try:
            await asyncio.wait_for(self.started.wait(), PROGRAM_START_TIMEOUT)
        except asyncio.TimeoutError:
            logger.debug("program never reported running; assuming it already ended")
            return
        await self.stopped.wait()

    def close(self) -> None:
        self._subscription.dispose()


async def stop_program_and_settle(hub: PybricksHubBLE) -> None:
    await hub.stop_user_program()
    await asyncio.sleep(STOP_PROGRAM_SETTLE)


async def unless_busy(hub: PybricksHubBLE, operation: Callable[[], Awaitable[None]]) -> None:
    """Run a hub operation, stopping a running program first if it is in the way."""
    if hub.status_observable.value & StatusFlag.USER_PROGRAM_RUNNING:
        logger.info("hub is running a program, stopping it")
        await stop_program_and_settle(hub)
    for attempt in range(STOP_PROGRAM_RETRIES + 1):
        try:
            await operation()
            return
        except BleakGATTProtocolError as e:
            # Status reports arrive asynchronously, so a running program may only show up as BUSY.
            if e.args[0] != CommandError.BUSY or attempt == STOP_PROGRAM_RETRIES:
                raise
            logger.info("hub is busy running a program, stopping it")
            await stop_program_and_settle(hub)


async def disconnect_quietly(hub: PybricksHubBLE) -> None:
    try:
        await hub.disconnect()
    except Exception as e:  # the link is usually already broken here
        logger.debug("disconnect failed: %s", e)


async def connect(args: argparse.Namespace, prepare: Callable[[PybricksHubBLE], Awaitable[None]]) -> PybricksHubBLE:
    """Connect and run ``prepare``, retrying both on BLE failures. The caller must disconnect."""
    for attempt in range(1, args.attempts + 1):
        logger.info("scanning for hub %s...", args.hub_name or "(any Pybricks hub)")
        try:
            device = await find_device(args.hub_name, timeout=args.scan_timeout)
        except asyncio.TimeoutError:
            raise HubNotFound(f"no hub found within {args.scan_timeout:.0f} s") from None
        hub = PybricksHubBLE(device)
        try:
            await hub.connect()
            logger.info("connected to %s, Pybricks firmware %s", device.name, hub.fw_version)
            # pybricksdev reads these hub capabilities on connect; there is no public accessor.
            logger.info("hub limits: program %d bytes, write %d bytes", hub._max_user_program_size, hub._max_write_size)
            await prepare(hub)
            return hub
        except RETRY_ERRORS as e:
            await disconnect_quietly(hub)
            if attempt == args.attempts:
                raise
            logger.warning("attempt %d/%d failed: %s; retrying", attempt, args.attempts, error_text(e))
            await asyncio.sleep(CONNECT_RETRY_DELAY)
    raise AssertionError("unreachable")


async def print_hub_output(hub: PybricksHubBLE, timestamps: bool) -> None:
    while True:
        line = await hub.read_line()
        if timestamps:
            print(f"{datetime.now():%H:%M:%S.%f}"[:-3], line, flush=True)
        else:
            print(line, flush=True)


async def run_and_stream(args: argparse.Namespace, path: Path) -> int:
    """Upload and start ``path``, print its output until it ends; Ctrl-C stops it."""
    watcher: ProgramWatcher | None = None

    async def start(hub: PybricksHubBLE) -> None:
        nonlocal watcher
        if watcher:
            watcher.close()
        watcher = ProgramWatcher(hub)
        limit_chunk_size(hub, args.chunk_size)
        await hub.run(str(path), wait=False, print_output=False)

    hub = await connect(args, lambda hub: unless_busy(hub, lambda: start(hub)))
    output = asyncio.create_task(print_hub_output(hub, args.timestamps))
    stopped = asyncio.create_task(watcher.wait_stopped())
    program_ended = False
    try:
        done, _ = await asyncio.wait([output, stopped], return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()  # re-raise failures, e.g. HubDisconnectError
        program_ended = True
        await asyncio.sleep(OUTPUT_FLUSH_DELAY)
        logger.info("hub program ended")
        return 0
    except HubDisconnectError:
        logger.error("hub disconnected")
        return 1
    finally:
        for task in (output, stopped):
            task.cancel()
        await asyncio.gather(output, stopped, return_exceptions=True)
        watcher.close()
        if not program_ended and hub.connection_state_observable.value == ConnectionState.CONNECTED:
            try:
                await hub.stop_user_program()
            except Exception as e:  # best effort during teardown
                logger.debug("stopping hub program failed: %s", e)
        await disconnect_quietly(hub)


async def cmd_scan(args: argparse.Namespace) -> int:
    flags = {name: True for name, on in (("WATCH", args.watch), ("REMOTE", args.remote)) if on}
    with tempfile.TemporaryDirectory(prefix="pybricks-investigate-") as tmp:
        with program.build(program.scan_program(), flags, directory=Path(tmp)) as path:
            return await run_and_stream(args, path)


async def cmd_run(args: argparse.Namespace) -> int:
    flags = {"DEBUG": True} if args.debug else {}
    with program.build(args.program, flags) as path:
        return await run_and_stream(args, path)


async def cmd_compile(args: argparse.Namespace) -> int:
    image = await program.compile_program(args.program)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(image)
    modules = ", ".join(program.image_modules(image))
    logger.info("compiled %s -> %s (%d bytes; modules: %s)", args.program, args.output, len(image), modules)
    return 0


async def cmd_stop(args: argparse.Namespace) -> int:
    hub = await connect(args, lambda hub: hub.stop_user_program())
    await disconnect_quietly(hub)
    logger.info("hub program stopped")
    return 0


COMMANDS = {
    "scan": (cmd_scan, "report the hub and the devices on its ports"),
    "run": (cmd_run, "upload and run a hub program, printing its output until it ends"),
    "compile": (cmd_compile, "compile locally into the hub upload image (no hub needed)"),
    "stop": (cmd_stop, "stop the program running on the hub"),
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="pybricks-investigate", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    hub_options = argparse.ArgumentParser(add_help=False)
    hub_options.add_argument("-n", "--hub-name", help="hub Bluetooth name or address (default: first found)")
    hub_options.add_argument(
        "--scan-timeout", type=float, default=10.0, help="BLE scan timeout in s (default: %(default)s)"
    )
    hub_options.add_argument("--attempts", type=int, default=3, help="connect/upload attempts (default: %(default)s)")
    output_options = argparse.ArgumentParser(add_help=False)
    output_options.add_argument("-t", "--timestamps", action="store_true", help="prefix hub output with the PC time")
    output_options.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help="program bytes per upload write, capped to the hub's maximum (default: %(default)s; "
        "150, the Technic Hub maximum, stalls uploads)",
    )

    commands = parser.add_subparsers(dest="command", required=True)
    parents = {"scan": [hub_options, output_options], "run": [hub_options, output_options], "stop": [hub_options]}
    subs = {}
    for name, (_, help_text) in COMMANDS.items():
        subs[name] = commands.add_parser(name, help=help_text, description=help_text, parents=parents.get(name, []))
    subs["scan"].add_argument("-w", "--watch", action="store_true", help="keep reporting plug/unplug and value changes")
    subs["scan"].add_argument("-r", "--remote", action="store_true", help="also look for a Powered Up remote")
    subs["run"].add_argument("program", type=Path, help="hub program (.py)")
    subs["run"].add_argument("--debug", action="store_true", help="switch the program's DEBUG = False line on")
    subs["compile"].add_argument("program", type=Path, help="hub program (.py)")
    subs["compile"].add_argument("-o", "--output", type=Path, help="output file (default: build/<program>.bin)")

    args = parser.parse_args(argv)
    if getattr(args, "attempts", 1) < 1:
        parser.error("--attempts must be at least 1")
    if getattr(args, "chunk_size", 1) < 1:
        parser.error("--chunk-size must be at least 1")
    if args.command == "compile" and args.output is None:
        args.output = Path("build") / args.program.with_suffix(".bin").name
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S", stream=sys.stderr
    )
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    try:
        return asyncio.run(COMMANDS[args.command][0](args))
    except KeyboardInterrupt:
        return 130
    except (HubNotFound, OSError, BleakError, RuntimeError, ValueError) as e:
        logger.error("%s", error_text(e))
        return 1
