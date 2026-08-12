import sys

import uvicorn

from cairn_api.knowledge.object_store import bootstrap_object_store
from cairn_api.maintenance.auth_cleanup import run_auth_cleanup
from cairn_api.settings import Settings


def main() -> int:
    if sys.argv[1:] == ["auth-cleanup"]:
        return run_auth_cleanup()
    if sys.argv[1:] == ["object-store-bootstrap"]:
        settings = Settings()
        object_store = bootstrap_object_store(
            settings,
            allowed_origins=settings.cors_origins,
        )
        try:
            return 0
        finally:
            object_store.close()
    if len(sys.argv) > 1:
        print("Usage: cairn-api [auth-cleanup|object-store-bootstrap]", file=sys.stderr)
        return 2

    settings = Settings()
    uvicorn.run(
        "cairn_api.app:app",
        host=settings.bind_host,
        port=settings.http_port,
        log_level=settings.log_level.lower(),
        proxy_headers=False,
    )
    return 0
