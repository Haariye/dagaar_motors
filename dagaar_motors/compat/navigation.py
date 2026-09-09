from __future__ import annotations

from dagaar_motors.compat.version import is_v16_or_newer


def desk_route(workspace: str = "dagaar-motors") -> str:
    prefix = "/desk" if is_v16_or_newer() else "/app"
    return f"{prefix}/{workspace}"