from rest_framework.throttling import SimpleRateThrottle


class ClientRateThrottle(SimpleRateThrottle):
    """30 requests a minute per client, one bucket shared by both POST endpoints
    (rate in REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["api"]). The client address
    honours NUM_PROXIES, so behind the host's proxy it comes from X-Forwarded-For."""

    scope = "api"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}
