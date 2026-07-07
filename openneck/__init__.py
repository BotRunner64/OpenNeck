"""OpenNeck active vision driver package."""

__version__ = "0.1.0"

__all__ = ["Config", "OpenNeckController", "load_config"]


def __getattr__(name: str):
    if name == "OpenNeckController":
        from .api import OpenNeckController

        return OpenNeckController
    if name in {"Config", "load_config"}:
        from .cli import Config, load_config

        return {"Config": Config, "load_config": load_config}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
