from importlib import import_module
from importlib.metadata import version


def test_worker_and_api_packages_resolve_from_the_workspace() -> None:
    cairn_api = import_module("cairn_api")
    cairn_worker = import_module("cairn_worker")

    assert version("cairn-api") == "0.1.0"
    assert version("cairn-worker") == "0.1.0"
    assert cairn_api.__package__ == "cairn_api"
    assert cairn_worker.__package__ == "cairn_worker"


def test_runtime_and_parser_dependencies_are_importable() -> None:
    for module_name in (
        "boto3",
        "httpx",
        "pgvector",
        "bs4",
        "openpyxl",
        "pypdf",
        "docx",
        "pptx",
    ):
        assert import_module(module_name).__name__ == module_name
