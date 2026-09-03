#!/usr/bin/env python3
"""Development entrypoint: `python run_api.py` (or `uvicorn app.main:app --reload`)."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "app"))

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=os.environ.get("API_HOST", "127.0.0.1"),
        port=int(os.environ.get("API_PORT", "8000")),
        reload=bool(os.environ.get("API_RELOAD", "1") == "1"),
        app_dir=str(Path(__file__).resolve().parent / "app"),
    )
