"""Cancellable pools for read-only photo processing; never used for transfers."""
import contextlib
import os
import signal
from concurrent.futures import ProcessPoolExecutor, TimeoutError

from engine import fileinfo, runtime


def initialize(exiftool_supported, log_dir):
    # A worker and its decoder children own one group. Establish it before ExifTool
    # starts, so cancelling can stop descendants without signalling the engine.
    os.setsid()
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    fileinfo._init_worker_process(exiftool_supported, log_dir)


def stop(executor):
    """Stop only this pool's processes and decoder descendants, then let shutdown reap.

    Python 3.11 has no public terminate_workers API. Keep the version-specific
    process lookup here and cover it with real subprocess cancellation tests.
    An uninterruptible kernel wait can still delay shutdown; never release the
    engine lock or report cancellation complete while its workers remain alive.
    """
    for process in list(executor._processes.values()):
        if not process.is_alive():
            continue
        try:
            if os.getpgid(process.pid) == process.pid:
                os.killpg(process.pid, signal.SIGKILL)
            else:
                # Cancellation may arrive before the initializer establishes its
                # group. No decoder has been launched at that point.
                process.kill()
        except ProcessLookupError:
            pass


@contextlib.contextmanager
def pool(max_workers, exiftool_supported, log_dir):
    executor = ProcessPoolExecutor(max_workers=max_workers, initializer=initialize,
                                   initargs=(exiftool_supported, log_dir))
    try:
        yield executor
    finally:
        if runtime.cancel_requested.is_set():
            runtime.logger.info("Stopping read-only photo workers at the user's request; recorded results are kept.")
            stop(executor)
        executor.shutdown(wait=True, cancel_futures=True)


def results(futures):
    """Keep submission order/batch bounds, but observe cancellation while waiting."""
    for future in futures:
        while not runtime.cancel_requested.is_set():
            try:
                value = future.result(timeout=0.25)
            except TimeoutError:
                if future.done():
                    raise  # A task raised TimeoutError itself, not a polling timeout.
                continue
            yield value
            break
        if runtime.cancel_requested.is_set():
            return
