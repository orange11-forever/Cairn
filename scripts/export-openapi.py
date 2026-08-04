import argparse
import json
from pathlib import Path

from cairn_api.app import create_app
from cairn_api.settings import Settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    settings = Settings(
        environment="test",
        database_url="postgresql+psycopg://cairn:cairn-local-only@127.0.0.1:5432/cairn_test",
        app_url="http://localhost:5500",
        cors_origins=["http://localhost:5500"],
        csrf_secret="openapi-export-only-secret-with-at-least-32-bytes",
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )
    serialized = json.dumps(
        create_app(settings).openapi(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    args.output.write_text(f"{serialized}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
