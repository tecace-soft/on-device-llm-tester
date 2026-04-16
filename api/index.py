"""Vercel Serverless Function entry point for the FastAPI backend.

Architecture: DEPLOYMENT_ARCHITECTURE.md §7
Used by: Vercel @vercel/python runtime (auto-detects the ``app`` ASGI export)
Depends on: main.app (FastAPI instance), sibling modules in api/

Why a separate entry file?
    Vercel's Python runtime discovers functions under ``api/*.py`` at project
    root and expects each to expose a WSGI/ASGI ``app``. We re-use the exact
    same FastAPI app defined in ``main.py`` so there is zero divergence
    between local ``uvicorn main:app`` and the serverless deployment.

Path routing:
    ``vercel.json`` rewrites ``/api/*`` and ``/health`` to this function.
    FastAPI then matches its own internally-registered routes (``/api/...``
    and ``/health``), unchanged from the existing implementation.
"""

from main import app

# Vercel's ASGI adapter picks up this symbol by name.
__all__ = ["app"]
