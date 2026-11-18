import logging
import time

from .web_push import deliver
from .db import session_factory
from .retention import cleanup
from .ranking import train
from .activity_job import process_room_activity

logger = logging.getLogger(__name__)


def main():
    factory = session_factory()
    next_cleanup = 0
    while True:
        try:
            with factory() as db:
                process_room_activity(db)
                train(db, automatic=True)
            with factory() as db:
                deliver(db)
            if time.monotonic() >= next_cleanup:
                with factory.begin() as db:
                    counts = cleanup(db)
                logger.info("Retention summary: %s", counts)
                next_cleanup = time.monotonic() + 3600
        except Exception as exc:
            # Database exceptions can contain bound parameters.
            logger.error("Retention job failed: %s", type(exc).__name__)
        time.sleep(60)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
