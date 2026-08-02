import logging
import sys
from typing import TextIO

HANDLER_MARKER = "_cairn_handler"


def configure_app_logging(level: str, stream: TextIO | None = None) -> logging.Logger:
    logger = logging.getLogger("cairn_api")
    for handler in list(logger.handlers):
        if getattr(handler, HANDLER_MARKER, False):
            logger.removeHandler(handler)
            handler.close()

    handler = logging.StreamHandler(stream or sys.stderr)
    setattr(handler, HANDLER_MARKER, True)
    handler.setFormatter(
        logging.Formatter(
            "%(levelname)s %(name)s request_id=%(request_id)s %(message)s",
            defaults={"request_id": "-"},
        )
    )
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger
