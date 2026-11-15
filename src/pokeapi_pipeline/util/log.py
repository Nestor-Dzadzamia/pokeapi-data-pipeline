import logging
import sys

from pokeapi_pipeline.util.config import Settings

LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s"


def _log_crash(exc_type, exc_value, exc_traceback) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logging.getLogger("pokeapi_pipeline").critical("crashed", exc_info=(exc_type, exc_value, exc_traceback))


def setup_logging(settings: Settings) -> None:
    """send every log line, and the traceback of any crash, to the terminal and to one log file"""
    settings.log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=settings.log_level,
        format=LOG_FORMAT,
        handlers=[logging.FileHandler(settings.log_file, encoding="utf-8"), logging.StreamHandler()],
        force=True,
    )
    sys.excepthook = _log_crash
