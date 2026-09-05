"""NINJA Social Intelligence Foundation, Part IV §61: Instagram content objective taxonomy. Every
content item must declare exactly one primary objective - format/creative strategy depends on it
(spec §61's own "do not optimize every post for views" instruction)."""
from __future__ import annotations

import enum


class ContentObjective(str, enum.Enum):
    REACH = "reach"
    SHARES = "shares"
    SAVES = "saves"
    COMMENTS = "comments"
    FOLLOWS = "follows"
    PROFILE_VISITS = "profile_visits"
    PRODUCT_CLICK = "product_click"
    BRAND = "brand"
