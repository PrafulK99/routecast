"""Provider failures. Messages never include a URL or a token."""


class ProviderError(Exception):
    pass


class NoRouteError(ProviderError):
    """The routing provider found no drivable route between the points."""


class RoutingUnavailableError(ProviderError):
    """The routing provider failed, after one retry where a retry makes sense."""


class WeatherUnavailableError(ProviderError):
    """The weather provider failed for every location."""


class WeatherRateLimitedError(ProviderError):
    """The weather provider answered 429; retrying straight away would not help."""
