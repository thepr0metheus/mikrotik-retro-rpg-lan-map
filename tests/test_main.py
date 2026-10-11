"""The way in, as Docker runs it: `python -m lan_map` starts the map, and SIGTERM stops it."""
import os
import signal
import socket
import subprocess
import sys
import time
import unittest
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent.parent


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class StoppingTest(unittest.TestCase):
    def test_sigterm_ends_the_map_at_once_and_cleanly(self):
        """In its container the map is PID 1, where SIGTERM with no handler does nothing: Docker
        waits ten seconds and kills it, and DSM's proxy answers 502 all that while. Out of a
        container SIGTERM with no handler kills at once, code -15. Code 0 is the handler's."""
        port = free_port()
        with TemporaryDirectory() as data:
            env = {key: value for key, value in os.environ.items() if not key.startswith("LAN_MAP_")}
            env.update(LAN_MAP_HOST="127.0.0.1", LAN_MAP_PORT=str(port), LAN_MAP_DATA_DIR=data,
                       LAN_MAP_REFRESH_MINUTES="0", LAN_MAP_NAMES_MINUTES="0")
            running = subprocess.Popen([sys.executable, "-m", "lan_map"], cwd=ROOT, env=env,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                self.wait_until_it_answers(port)
                running.send_signal(signal.SIGTERM)
                self.assertEqual(running.wait(timeout=5), 0)
            finally:
                if running.poll() is None:
                    running.kill()
                    running.wait()

    @staticmethod
    def wait_until_it_answers(port: int) -> None:
        deadline = time.monotonic() + 10
        while True:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1) as answer:
                    if answer.status == 200:
                        return
            except OSError:
                if time.monotonic() > deadline:
                    raise
            time.sleep(0.1)


if __name__ == "__main__":
    unittest.main()
