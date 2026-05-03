"""Bridge LiveKit room audio → event_bus → visitor_ws.

Subscribes to a LiveKit room's mixed audio track, forwards Opus frames
to the existing visitor_ws broadcast (mode "live").

Will be wired in Sprint E.
"""
from __future__ import annotations

# Implementation arrives in Sprint E
