import sys
from importlib import import_module
from importlib.metadata import version
from subprocess import run


def test_worker_and_api_packages_resolve_from_the_workspace() -> None:
    cairn_api = import_module("cairn_api")
    cairn_worker = import_module("cairn_worker")

    assert version("cairn-api") == "0.1.0"
    assert version("cairn-worker") == "0.1.0"
    assert cairn_api.__package__ == "cairn_api"
    assert cairn_worker.__package__ == "cairn_worker"


def test_standalone_worker_registers_complete_foreign_key_metadata() -> None:
    script = """
import cairn_worker.runner
from cairn_api.db.base import Base
tables = {table.name for table in Base.metadata.sorted_tables}
required = {'users', 'organizations', 'projects', 'embedding_profiles', 'ingestion_batches'}
assert required <= tables, required - tables
for table in Base.metadata.sorted_tables:
    for foreign_key in table.foreign_keys:
        foreign_key.column
"""
    result = run([sys.executable, "-c", script], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


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
