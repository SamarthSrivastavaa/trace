"""Razorpay authoritative-state provider - BOUNDARY ONLY.

STATUS: NOT a working integration. No live call has ever been made from this
repository. The honest claim after this phase is exactly:

    "A Razorpay provider boundary exists; live acquisition remains unverified
     until a successful test-mode call."

Do not describe this as 'Razorpay integrated' anywhere.

What IS done here:
  - the SDK/HTTP surface is isolated behind AuthoritativeStateProvider
  - configuration is explicit and validated
  - importing this module requires no credentials and performs no I/O
  - external responses would be mapped to plain primitives before returning

What is NOT done, deliberately rather than by omission: the exact resource ->
field mapping. Guessing endpoint shapes would produce a provider that looks
finished and fails on first contact. The precise gaps are listed in
REQUIRED_RESOURCE_MAPPING below and must be filled from real test-mode
responses, not from documentation alone.
"""

import os

from ...state.contract import (AuthoritativeState, StateRequest, StateSource,
                               require_primitive_state)
from ...state.errors import (MalformedProviderState, ProviderFailure,
                             ProviderNotConfigured)

API_BASE = "https://api.razorpay.com/v1"

# Each entry: production snapshot field <- the Razorpay resource that supplies
# it. TODO markers are the exact unknowns blocking a live implementation.
REQUIRED_RESOURCE_MAPPING = {
    "offers[].percent":            "TODO: Offers API - confirm field name and whether percent is int or string",
    "offers[].flat_amount_minor":  "TODO: Offers API - confirm minor-unit representation",
    "offers[].valid_until":        "TODO: Offers API - confirm timestamp format and timezone offset presence",
    "offers[].active":             "TODO: Offers API - confirm active/status field",
    "subscription.attempt_index":  "TODO: Subscriptions API - confirm whether retry index is exposed at all",
    "subscription.max_attempts":   "TODO: Subscriptions API - may be an NPCI/plan constant, not an API field",
    "payment.status":              "Payments API - status",
    "payment.amount_minor":        "Payments API - amount (already minor units)",
    "cart.item_count":             "TODO: Orders API - line items may require a separate fetch",
    "cart.total_minor":            "Orders API - amount (already minor units)",
    "customer.tier":               "TODO: not a Razorpay concept; merchant-supplied or unsupported",
    "customer.opted_out":          "TODO: not a Razorpay concept; suppression is Attest-side state",
}


class RazorpayConfig:
    """Explicit configuration. Reads env only when constructed, never at import."""

    def __init__(self, key_id: str | None = None, key_secret: str | None = None):
        self.key_id = key_id or os.environ.get("RAZORPAY_KEY_ID", "")
        self.key_secret = key_secret or os.environ.get("RAZORPAY_KEY_SECRET", "")

    @property
    def is_test_mode(self) -> bool:
        return self.key_id.startswith("rzp_test_")

    def require(self) -> None:
        if not self.key_id or not self.key_secret:
            raise ProviderNotConfigured(
                "RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET are required for the "
                "live provider; use FixtureStateProvider for offline runs")
        if not self.is_test_mode:
            raise ProviderNotConfigured(
                f"refusing to run against a non-test key ({self.key_id[:8]}...); "
                "this project is test-mode only")


class RazorpayStateProvider:
    """Live authoritative state. Import-safe; construction validates config."""

    name = "razorpay"

    def __init__(self, config: RazorpayConfig | None = None, session=None):
        self.config = config or RazorpayConfig()
        self.config.require()          # fail loudly, at construction
        self._session = session        # injected for testing; no default client

    def get_state(self, request: StateRequest) -> AuthoritativeState:
        raise ProviderFailure(
            "RazorpayStateProvider is a boundary skeleton: the resource->field "
            "mapping is unresolved. See REQUIRED_RESOURCE_MAPPING. Refusing to "
            "guess endpoint shapes and report a live integration that has never "
            "made a call.")

    # -- the part that IS finished, and independently testable ---------------

    @staticmethod
    def to_primitive_state(raw: dict) -> dict:
        """Map an external response into plain primitive state.

        Runs require_primitive_state so an SDK object, Decimal or float can
        never reach canonicalisation or the adjudicator.
        """
        if not isinstance(raw, dict):
            raise MalformedProviderState(
                f"expected an object from the API, got {type(raw).__name__}")
        try:
            require_primitive_state(raw)
        except MalformedProviderState:
            raise
        return raw

    @staticmethod
    def unresolved_mappings() -> list[str]:
        return sorted(k for k, v in REQUIRED_RESOURCE_MAPPING.items()
                      if v.startswith("TODO"))
