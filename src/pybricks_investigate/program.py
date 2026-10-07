"""Hub program handling that needs no hub: flag switches, temporary builds, compilation."""

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

from pybricksdev.compile import compile_multi_file

# Bytecode format of Pybricks v3.2+ firmware; the hub may also accept newer ones.
MPY_ABI = 6


def scan_program() -> Path:
    return Path(str(resources.files(__package__) / "hub" / "scan.py"))


def set_flags(text: str, flags: dict[str, bool]) -> str:
    """Switch ``NAME = False`` lines to the given values; each must appear exactly once."""
    for name, value in flags.items():
        line = f"{name} = False"
        if text.count(line) != 1:
            raise ValueError(f"program must contain exactly one {line!r} line")
        text = text.replace(line, f"{name} = {value}")
    return text


@contextmanager
def build(path: Path, flags: dict[str, bool], directory: Path | None = None) -> Iterator[Path]:
    """The program with ``flags`` switched, as a temporary file (the original if there is nothing to change).

    The copy goes into ``directory`` (default: next to the program, so local imports still resolve).
    """
    if not flags:
        yield path
        return
    text = set_flags(path.read_text(), flags)
    # The name must be a valid module name for pybricksdev's compiler.
    with tempfile.NamedTemporaryFile(
        "w", dir=directory or path.parent, prefix=f"_{path.stem}_build_", suffix=".py"
    ) as f:
        f.write(text)
        f.flush()
        yield Path(f.name)


async def compile_program(path: Path) -> bytes:
    """The upload image pybricksdev sends to the hub: per module a uint32 LE size,
    the zero-terminated module name and its MicroPython bytecode."""
    return await compile_multi_file(str(path), MPY_ABI)


def image_modules(image: bytes) -> dict[str, bytes]:
    """Split an upload image into module name -> bytecode."""
    modules = {}
    offset = 0
    while offset < len(image):
        size = int.from_bytes(image[offset : offset + 4], "little")
        name_end = image.index(b"\0", offset + 4)
        modules[image[offset + 4 : name_end].decode()] = image[name_end + 1 : name_end + 1 + size]
        offset = name_end + 1 + size
    return modules
