from __future__ import annotations

import os
import sys
from multiprocessing import util


def exit_quietly() -> None:
    # nanobind extensions (soxr, ctranslate2) print leak reports during interpreter teardown.
    # Running multiprocessing's own exit handler keeps the clean-up that matters, such as
    # unlinking named semaphores, and os._exit then skips the teardown that prints the noise.
    util._exit_function()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
