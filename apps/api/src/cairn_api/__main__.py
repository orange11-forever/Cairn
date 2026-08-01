import uvicorn

from cairn_api.settings import Settings


def main() -> None:
    settings = Settings()
    uvicorn.run(
        "cairn_api.app:app",
        host=settings.bind_host,
        port=settings.http_port,
        log_level=settings.log_level.lower(),
    )
