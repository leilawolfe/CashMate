import pkgutil
from importlib import import_module

# /d:/MyData/Personal/CashMate/__init__.py
# Expose prompt.py in the package namespace so child packages can import it easily.


# support namespace package extension if needed
__path__ = pkgutil.extend_path(__path__, __name__)

# try to import the module into the package namespace (so `from CashMate import prompt` works)
try:
    prompt = import_module("src.prompt", __name__)
except Exception:
    # keep attribute present (None) if prompt.py is not available at import time
    prompt = None

__all__ = ["prompt"]