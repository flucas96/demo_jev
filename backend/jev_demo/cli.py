"""Run the built demo on a single local origin."""

import uvicorn


def main() -> None:
    """Serve the Python API and the compiled React application on localhost."""
    uvicorn.run("jev_demo.app:app", host="127.0.0.1", port=8000)
