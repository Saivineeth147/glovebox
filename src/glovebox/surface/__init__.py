"""The perception/action seam.

`Surface` is the only thing that knows how to *see* and *touch* an application. Everything
above it (agent loop, replay engine, operator console) speaks in `Observation`, `Element`,
`Target` and `Condition`. Swapping the web implementation for an accessibility-tree or
screenshot-driven desktop implementation means implementing this protocol, not touching the
artifact schema or the replay engine (REPORT.md §4).
"""

from .base import DialogInfo, Element, Observation, Resolved, Surface, SurfaceError
from .web.playwright_surface import PlaywrightSurface

__all__ = [
    "DialogInfo",
    "Element",
    "Observation",
    "PlaywrightSurface",
    "Resolved",
    "Surface",
    "SurfaceError",
]
