"""Clawd Buddy — animated terminal pet that reacts to coding assistant events."""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__ = _pkg_version("clawd-buddy")
except PackageNotFoundError:
    # Running from a source checkout where the package metadata is not yet
    # registered (e.g. before `pip install -e .` or in a CI step that runs
    # tests against the raw tree). Fallback keeps imports working so the
    # buddy can still launch from `python -m clawd_buddy.app`.
    __version__ = "0.0.0+source"

__all__ = ["__version__"]
