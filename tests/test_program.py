import asyncio
from pathlib import Path

import pytest

from pybricks_investigate import program

EXAMPLE = Path(__file__).parent.parent / "hub" / "example.py"


def test_set_flags_switches_named_lines():
    text = "WATCH = False\nREMOTE = False\n"
    assert program.set_flags(text, {"WATCH": True}) == "WATCH = True\nREMOTE = False\n"


def test_set_flags_requires_single_line():
    with pytest.raises(ValueError):
        program.set_flags("x = 1\n", {"DEBUG": True})
    with pytest.raises(ValueError):
        program.set_flags("DEBUG = False\nDEBUG = False\n", {"DEBUG": True})


def test_build_without_flags_is_original(tmp_path):
    source = tmp_path / "prog.py"
    source.write_text("print(1)\n")
    with program.build(source, {}) as path:
        assert path == source


def test_build_is_temporary_copy_next_to_program(tmp_path):
    source = tmp_path / "prog.py"
    source.write_text("DEBUG = False\n")
    with program.build(source, {"DEBUG": True}) as path:
        assert path.parent == tmp_path
        assert path.read_text() == "DEBUG = True\n"
    assert not path.exists()
    assert source.read_text() == "DEBUG = False\n"


@pytest.mark.parametrize("flags", [{}, {"WATCH": True, "REMOTE": True}])
def test_scan_program_compiles(tmp_path, flags):
    with program.build(program.scan_program(), flags, directory=tmp_path) as path:
        image = asyncio.run(program.compile_program(path))
    assert {name: code[:2] for name, code in program.image_modules(image).items()} == {"__main__": b"M\x06"}


def test_example_compiles_including_debug_build():
    with program.build(EXAMPLE, {"DEBUG": True}) as path:
        assert list(program.image_modules(asyncio.run(program.compile_program(path)))) == ["__main__"]


def test_scan_program_is_package_data():
    assert program.scan_program().is_file()
