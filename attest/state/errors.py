"""Provider failure taxonomy.

These exist so the pipeline can tell three things apart that would otherwise
collapse into "something went wrong":

  StateUnavailable        the state we asked for does not exist
  ProviderFailure         the provider could not answer (transport, auth, bug)
  MalformedProviderState  the provider answered with something unusable

None of them is UNVERIFIABLE. UNVERIFIABLE is an ADJUDICATION outcome meaning
the authoritative state genuinely cannot settle a claim. Missing state is an
ACQUISITION failure - we never got to ask. Collapsing the two would let an
infrastructure outage look like an honest "we don't know".

SDK-specific exceptions must be caught inside a provider and re-raised as one
of these. Nothing below the provider boundary should ever see an
anthropic/razorpay/httpx exception type.
"""


class StateProviderError(Exception):
    """Base for every acquisition failure."""


class StateUnavailable(StateProviderError):
    """The requested state does not exist (unknown scenario, unknown merchant)."""


class ProviderFailure(StateProviderError):
    """The provider could not complete the request."""


class MalformedProviderState(StateProviderError):
    """The provider returned something that is not primitive JSON-like state."""


class ProviderNotConfigured(StateProviderError):
    """Required credentials or configuration are absent."""
