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

# Why this sys.path shim:
#   Vercel's Python runtime loads this file as a top-level module
#   (``vc__handler__python`` imports it) but does NOT add ``api/`` to
#   sys.path. Without this, ``from main import app`` raises
#   ``ModuleNotFoundError: No module named 'main'``, which is exactly
#   what the production logs showed after the first deploy.
#   Locally (``uvicorn main:app``) the CWD is already ``api/`` so this
#   is a no-op.
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from main import app

# Vercel's ASGI adapter picks up this symbol by name.
__all__ = ["app"]
