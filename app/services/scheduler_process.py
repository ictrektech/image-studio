"""Linux-only lease supervisor for scheduled sd-cli processes.

Survives backend exit long enough to stop its child on the persisted lease deadline.
"""
import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def atomic(path, value):
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w") as f:
        json.dump(value, f)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def child_setup():
    os.setsid()
    # If this supervisor is killed, the actual computation is killed as well.
    parent = os.getppid()
    if ctypes.CDLL(None).prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
        os._exit(126)
    if os.getppid() != parent:
        os._exit(126)


def main():
    lease = Path(sys.argv[1])
    marker = lease.with_suffix(".process")
    if not sys.platform.startswith("linux"):
        raise RuntimeError("scheduled sd-cli lease supervisor requires Linux")
    birth = Path(f"/proc/{os.getpid()}/stat").read_text().rsplit(")", 1)[1].split()[19]
    atomic(marker, {"pid": os.getpid(), "birth": birth, "stopped": False})
    proc = subprocess.Popen(sys.argv[2:], preexec_fn=child_setup)
    child_birth = Path(f"/proc/{proc.pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    atomic(marker, {"pid": os.getpid(), "birth": birth, "child_pid": proc.pid, "child_birth": child_birth, "stopped": False})
    stopping = False
    def stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while proc.poll() is None:
            try:
                expired = json.loads(lease.read_text()).get("deadline", 0) <= time.monotonic()
            except (OSError, ValueError):
                expired = True
            if stopping or expired:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
                break
            time.sleep(0.1)
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
        atomic(marker, {"pid": os.getpid(), "birth": birth, "stopped": True})
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
