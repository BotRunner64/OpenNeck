"""OpenNeck active vision driver package."""

__version__ = "0.1.0"

from .api import OpenNeckController
from .cli import Config, load_config

__all__ = ["Config", "OpenNeckController", "load_config"]
