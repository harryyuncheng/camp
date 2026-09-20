#!/usr/bin/env python3
"""The Ramp sandbox bridge now lives in the FastAPI service (camp.ramp, mounted at /v1/ramp) and stores its
allocation attempts in the shared database. Run the one backend instead:

    cd backend && uv run uvicorn camp.api:app --port 8788
"""
import sys

if __name__ == "__main__":
    sys.exit("backend/server.py is retired: run `uv run uvicorn camp.api:app --port 8788` (Ramp is served at /v1/ramp).")
