"""Deep link for the Plex stream details button and the embed title.

Discord only accepts ``http(s)`` URLs on link buttons, so a ``plex://`` scheme is
out. On ``app.plex.tv`` that costs nothing: the Plex mobile apps claim those web
links as universal/app links themselves, so the phone opens the app and the
desktop the browser. A self hosted Plex Web base keeps the same route but loses
that hand-off - the phone stays in the browser.
"""

from typing import Any, Optional
from urllib.parse import quote


def web_rating_key(session: Any) -> Optional[Any]:
    """Return the rating key Plex Web expects for the item of a session.

    Plex Web has no page for a single track, so music points at the album - the
    same substitution Tautulli makes for its ``plex_url`` parameter.
    """
    if getattr(session, "type", "") == "track":
        return getattr(session, "parentRatingKey", None)
    return getattr(session, "ratingKey", None)


def build_plex_web_url(machine_identifier: Any, rating_key: Any, base_url: Any) -> Optional[str]:
    """Build the Plex Web deep link for a library item.

    The route behind ``base_url`` is the same one Tautulli builds for its
    ``{plex_url}`` parameter, and it is served both by ``app.plex.tv`` and by the
    Plex Web app a server hosts itself.

    Returns ``None`` when a part is missing - a half built link would send the
    user to an empty Plex Web app.
    """
    identifier = str(machine_identifier or "").strip()
    key = str(rating_key or "").strip()
    base = str(base_url or "").strip().rstrip("/")

    if not identifier or not key or not base:
        return None

    metadata_path = quote(f"/library/metadata/{key}", safe="")
    return f"{base}#!/server/{identifier}/details?key={metadata_path}"
