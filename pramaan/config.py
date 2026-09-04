"""Application configuration.

DELIBERATE DESIGN: this object holds NO SECRETS.

It holds *selectors* - which state provider, which proposer, which policy file,
which database. Each integration reads its own credential from the environment
at construction (AnthropicTransport reads ANTHROPIC_API_KEY, RazorpayConfig
reads RAZORPAY_KEY_*). Because no secret is ever stored here, a config object
cannot leak one through repr(), logs, a manifest, or a proof - there is nothing
to redact.

Selecting `claude` or `razorpay` does not read a credential either; it only
records the intent. The credential check happens when the component is
constructed, and fails with the typed error that component already defines.
"""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass
from enum import Enum


class ConfigError(ValueError):
    """The configuration is not usable."""


class StateProviderChoice(str, Enum):
    FIXTURE = "fixture"          # SIMULATED, no credentials
    RAZORPAY = "razorpay"        # LIVE, credentials required


class ProposerChoice(str, Enum):
    FIXTURE = "fixture"          # deterministic mock, no credentials
    CLAUDE = "claude"            # LIVE, credentials required


DEFAULT_DB = "pramaan.db"


@dataclass(frozen=True)
class AppConfig:
    db_path: str = DEFAULT_DB
    state_provider: StateProviderChoice = StateProviderChoice.FIXTURE
    proposer: ProposerChoice = ProposerChoice.FIXTURE
    policy_path: str | None = None          # None -> bundled default policy

    @property
    def is_fully_simulated(self) -> bool:
        return (self.state_provider is StateProviderChoice.FIXTURE
                and self.proposer is ProposerChoice.FIXTURE)

    @property
    def mode_label(self) -> str:
        """What a UI or CLI must display. Never let simulated state read live."""
        state = ("SIMULATED" if self.state_provider is StateProviderChoice.FIXTURE
                 else "LIVE TEST MODE")
        model = ("MOCK" if self.proposer is ProposerChoice.FIXTURE else "LIVE")
        return f"state={state} model={model}"

    def requires_credentials(self) -> list[str]:
        """Which env vars the chosen components will demand. Names only."""
        needed = []
        if self.proposer is ProposerChoice.CLAUDE:
            needed.append("ANTHROPIC_API_KEY")
        if self.state_provider is StateProviderChoice.RAZORPAY:
            needed += ["RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET"]
        return needed

    def missing_credentials(self) -> list[str]:
        return [n for n in self.requires_credentials() if not os.environ.get(n)]

    @classmethod
    def from_env(cls, **overrides) -> "AppConfig":
        """Read selectors from the environment. Reads no secret."""
        def pick(enum_cls, env_name, default):
            raw = overrides.pop(env_name.lower().replace("pramaan_", ""), None)
            raw = raw or os.environ.get(env_name)
            if raw is None:
                return default
            value = raw.value if isinstance(raw, enum_cls) else str(raw).lower()
            try:
                return enum_cls(value)
            except ValueError:
                valid = [m.value for m in enum_cls]
                raise ConfigError(
                    f"{env_name}={raw!r} is not one of {valid}") from None

        state = pick(StateProviderChoice, "PRAMAAN_STATE_PROVIDER",
                     StateProviderChoice.FIXTURE)
        proposer = pick(ProposerChoice, "PRAMAAN_PROPOSER", ProposerChoice.FIXTURE)
        db = overrides.pop("db_path", None) or os.environ.get("PRAMAAN_DB", DEFAULT_DB)
        policy = overrides.pop("policy_path", None) or os.environ.get("PRAMAAN_POLICY")

        if overrides:
            raise ConfigError(f"unknown config override(s): {sorted(overrides)}")
        if policy is not None and not pathlib.Path(policy).is_file():
            raise ConfigError(f"policy file not found: {policy}")
        return cls(db_path=str(db), state_provider=state, proposer=proposer,
                   policy_path=str(policy) if policy else None)
