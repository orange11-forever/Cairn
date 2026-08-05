import sys

import uvicorn

from cairn_api.maintenance.auth_cleanup import run_auth_cleanup
from cairn_api.settings import Settings


def main() -> int:
    if sys.argv[1:] == ["auth-cleanup"]:
        return run_auth_cleanup()
    if len(sys.argv) > 1:
        print("Usage: cairn-api [auth-cleanup]", file=sys.stderr)
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
