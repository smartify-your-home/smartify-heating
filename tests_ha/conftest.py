"""Repo-eigene custom_components vor die des Test-Harness stellen."""
import pathlib
import sys

ROOT = str(pathlib.Path(__file__).resolve().parents[1])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
for name in [m for m in sys.modules if m == "custom_components" or m.startswith("custom_components.")]:
    del sys.modules[name]
import custom_components  # noqa: E402,F401
