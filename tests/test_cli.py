import argparse
import asyncio
from pathlib import Path

import pytest
from bleak.exc import BleakGATTProtocolError, BleakGATTProtocolErrorCode
from pybricksdev.ble.pybricks import CommandError, StatusFlag
from pybricksdev.connections import ConnectionState
from reactivex.subject import BehaviorSubject

from pybricks_investigate import cli, program

UNLIKELY = BleakGATTProtocolErrorCode.UNLIKELY_ERROR
EXAMPLE = Path(__file__).parent.parent / "hub" / "example.py"
RUNNING = StatusFlag.USER_PROGRAM_RUNNING


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(cli, "STOP_PROGRAM_SETTLE", 0)
    monkeypatch.setattr(cli, "CONNECT_RETRY_DELAY", 0)
    monkeypatch.setattr(cli, "PROGRAM_START_TIMEOUT", 0.05)
    monkeypatch.setattr(cli, "OUTPUT_FLUSH_DELAY", 0.05)


class FakeHub:
    """Programs follow ``script``: ("line", text) | ("status", flags) | ("sleep", s) steps after start."""

    fw_version = "3.6.1"
    _max_user_program_size = 16000
    _max_write_size = 155  # a Technic Hub: MTU 158

    def __init__(self, script=(), failures=None, status=None):
        self.status_observable = BehaviorSubject(status or StatusFlag(0))
        self.connection_state_observable = BehaviorSubject(ConnectionState.DISCONNECTED)
        self.script = list(script)
        self.failures = {k: list(v) for k, v in (failures or {}).items()}
        self.calls = []
        self.lines = asyncio.Queue()

    async def _call(self, name):
        self.calls.append(name)
        if self.failures.get(name):
            raise self.failures[name].pop(0)

    async def connect(self):
        await self._call("connect")
        self.connection_state_observable.on_next(ConnectionState.CONNECTED)

    async def disconnect(self):
        self.calls.append("disconnect")
        self.connection_state_observable.on_next(ConnectionState.DISCONNECTED)

    async def run(self, path, wait, print_output):
        await self._call("run")
        self.chunk_size = self._max_write_size - 5  # what pybricksdev's upload would use
        self.uploaded = Path(path).read_text()
        self.lines = asyncio.Queue()
        self.program = asyncio.get_running_loop().create_task(self._play())

    async def _play(self):
        for kind, value in self.script:
            if kind == "line":
                self.lines.put_nowait(value)
            elif kind == "status":
                self.status_observable.on_next(value)
            else:
                await asyncio.sleep(value)

    async def stop_user_program(self):
        self.calls.append("stop")
        self.status_observable.on_next(StatusFlag(0))

    async def read_line(self):
        return await self.lines.get()


def run_command(monkeypatch, argv, hubs):
    hubs = list(hubs)

    async def fake_find_device(name, timeout):
        return argparse.Namespace(name="Pybricks Hub")

    monkeypatch.setattr(cli, "find_device", fake_find_device)
    monkeypatch.setattr(cli, "PybricksHubBLE", lambda device: hubs.pop(0))
    args = cli.parse_args(argv)
    return asyncio.run(cli.COMMANDS[args.command][0](args))


def test_run_streams_output_including_lines_after_stop(monkeypatch, capsys):
    hub = FakeHub(
        [("status", RUNNING), ("line", "hello"), ("sleep", 0.01), ("status", StatusFlag(0)), ("line", "late tail")]
    )
    assert run_command(monkeypatch, ["run", str(EXAMPLE)], [hub]) == 0
    assert capsys.readouterr().out.splitlines() == ["hello", "late tail"]
    assert hub.calls == ["connect", "run", "disconnect"]  # ended by itself: not stopped


def test_short_program_without_running_status_still_ends(monkeypatch, capsys):
    hub = FakeHub([("line", "quick")])
    assert run_command(monkeypatch, ["run", str(EXAMPLE)], [hub]) == 0
    assert capsys.readouterr().out.splitlines() == ["quick"]


def test_leftover_running_flag_is_not_mistaken_for_this_program(monkeypatch, capsys):
    hub = FakeHub(
        [("status", RUNNING), ("sleep", 0.02), ("line", "mine"), ("status", StatusFlag(0))],
        failures={"run": [BleakGATTProtocolError(CommandError.BUSY)]},
    )
    run_command(monkeypatch, ["run", str(EXAMPLE)], [hub])
    assert hub.calls[:4] == ["connect", "run", "stop", "run"]
    assert capsys.readouterr().out.splitlines() == ["mine"]


def test_timestamps_option(monkeypatch, capsys):
    hub = FakeHub([("status", RUNNING), ("line", "x"), ("status", StatusFlag(0))])
    run_command(monkeypatch, ["run", "-t", str(EXAMPLE)], [hub])
    stamp, text = capsys.readouterr().out.split()
    assert text == "x" and stamp.count(":") == 2


def test_run_debug_switches_flag(monkeypatch):
    hub = FakeHub()
    run_command(monkeypatch, ["run", "--debug", str(EXAMPLE)], [hub])
    assert "DEBUG = True" in hub.uploaded
    assert not list(EXAMPLE.parent.glob("_*_build_*.py"))


@pytest.mark.parametrize(
    ("argv", "expected"),
    [([], ("WATCH = False", "REMOTE = False")), (["--watch", "--remote"], ("WATCH = True", "REMOTE = True"))],
)
def test_scan_uploads_bundled_program_with_flags(monkeypatch, argv, expected):
    hub = FakeHub()
    run_command(monkeypatch, ["scan", *argv], [hub])
    assert all(line in hub.uploaded for line in expected)
    assert "def scan_ports" in hub.uploaded


def test_upload_failure_reconnects_and_retries(monkeypatch):
    first = FakeHub(failures={"run": [BleakGATTProtocolError(UNLIKELY)]})
    second = FakeHub()
    assert run_command(monkeypatch, ["run", str(EXAMPLE)], [first, second]) == 0
    assert first.calls == ["connect", "run", "disconnect"]
    assert second.calls == ["connect", "run", "disconnect"]


def test_interrupted_stream_stops_the_program(monkeypatch):
    hub = FakeHub([("status", RUNNING), ("sleep", 3600)])

    async def main():
        async def fake_find_device(name, timeout):
            return argparse.Namespace(name="Pybricks Hub")

        monkeypatch.setattr(cli, "find_device", fake_find_device)
        monkeypatch.setattr(cli, "PybricksHubBLE", lambda device: hub)
        task = asyncio.create_task(cli.cmd_run(cli.parse_args(["run", str(EXAMPLE)])))
        await asyncio.sleep(0.05)
        task.cancel()  # what Ctrl-C does under asyncio.run
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(main())
    assert hub.calls == ["connect", "run", "stop", "disconnect"]


def test_compile_defaults_to_build_bin(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    args = cli.parse_args(["compile", str(EXAMPLE)])
    assert args.output == Path("build/example.bin")
    assert asyncio.run(cli.cmd_compile(args)) == 0
    assert list(program.image_modules(Path("build/example.bin").read_bytes())) == ["__main__"]


@pytest.mark.parametrize(
    ("argv", "chunk_size"), [([], 120), (["--chunk-size", "50"], 50), (["--chunk-size", "500"], 150)]
)
def test_upload_chunk_size_is_capped_below_the_hub_maximum(monkeypatch, argv, chunk_size):
    hub = FakeHub()
    run_command(monkeypatch, ["run", *argv, str(EXAMPLE)], [hub])
    assert hub.chunk_size == chunk_size


def test_hub_limits_are_logged(monkeypatch, caplog):
    caplog.set_level("INFO")
    run_command(monkeypatch, ["scan"], [FakeHub()])
    assert "hub limits: program 16000 bytes, write 155 bytes" in caplog.messages


def test_chunk_size_must_be_positive():
    with pytest.raises(SystemExit):
        cli.parse_args(["run", "--chunk-size", "0", str(EXAMPLE)])
