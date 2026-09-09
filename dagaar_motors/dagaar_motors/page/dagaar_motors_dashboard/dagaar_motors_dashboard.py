from __future__ import annotations

import frappe

from dagaar_motors.api.permissions import require_app_access


def get_context(context):
    require_app_access()
    context.no_cache = 1
    return context