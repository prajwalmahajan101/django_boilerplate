"""Custom DRF throttle classes for sensitive endpoints.

These run alongside any nginx-level rate limits as defence-in-depth.
nginx's 5r/s catches the obvious; this DRF-level throttle catches the
attacker that distributes across IPs nginx considers separate.
"""

from __future__ import annotations

from rest_framework.throttling import AnonRateThrottle


class AuthEndpointThrottle(AnonRateThrottle):
    """5 requests / minute per anonymous source IP for auth endpoints.

    Applied to login + token-refresh + similar primitives. Authenticated
    users have a much looser rate (the application throttles in
    ``core.resilience.throttles``); this class only narrows the door
    that an unauthenticated attacker can knock on.
    """

    scope = "auth_burst"
    rate = "5/min"
