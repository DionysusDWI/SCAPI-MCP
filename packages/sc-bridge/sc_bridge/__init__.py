"""Survivalcraft local bridge. No import-time game or filesystem changes."""
from .client import Bridge, BridgeError
from .config import Config

__version__ = '0.5.0'
PROTOCOL_VERSION = 3
__all__ = ['Bridge', 'BridgeError', 'Config']
