"""Disposable long-running worker; test only."""
import signal
import time
from pathlib import Path

keep_running = True
def stop(*_args):
    global keep_running
    keep_running = False
signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
while keep_running:
    Path("/run/uda-v2-worker.heartbeat").write_text("alive")
    time.sleep(0.25)
