from importlib.metadata import version

from cairn_api.__main__ import main


def test_package_has_version() -> None:
    assert version("cairn-api") == "0.1.0"


def test_console_entry_point_is_importable() -> None:
    assert callable(main)
