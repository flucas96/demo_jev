"""Launch the Python API and React development server together."""

import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    """Manage both development processes and clean them up on interruption."""
    npm = shutil.which("npm")
    if npm is None:
        raise SystemExit("Install Node.js and npm before starting the frontend.")
    processes: list[subprocess.Popen[bytes]] = []
    try:
        processes.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "jev_demo.app:app",
                    "--reload",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8000",
                    "--reload-dir",
                    "backend",
                ],
                cwd=ROOT,
            )
        )
        processes.append(
            subprocess.Popen(
                [npm, "run", "dev", "--", "--host", "127.0.0.1"], cwd=ROOT / "frontend"
            )
        )
        print("\nJev Decision Lab: http://127.0.0.1:5173\nAPI docs: http://127.0.0.1:8000/docs\n")
        while all(process.poll() is None for process in processes):
            time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    main()
