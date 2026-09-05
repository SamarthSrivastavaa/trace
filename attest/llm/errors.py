"""Proposer failure taxonomy.

Deliberately importable with no SDK and no credentials: attest.core.pipeline
imports these to map failures, and must not drag in the Anthropic SDK.

The distinctions exist so an outage is never recorded as a reasoning failure:

    ProposerNotConfigured   no credentials / SDK  -> infrastructure
    ProposerTransportFailure API or network error -> infrastructure
    ProposerTimeout          exceeded the deadline -> infrastructure
    ProposerMalformedOutput  no JSON object found  -> model output
    ProposerSchemaViolation  JSON present, rejected by the PRODUCTION schema

None of them ever produces a Proposal. A failed model call must never be
papered over with a fabricated proposal or a silent fall back to the mock.
"""


class ProposerError(Exception):
    """Base for every proposal-generation failure."""


class ProposerNotConfigured(ProposerError):
    """Credentials or the SDK are absent."""


class ProposerTransportFailure(ProposerError):
    """The provider could not be reached or returned an error."""


class ProposerTimeout(ProposerTransportFailure):
    """The provider did not answer within the deadline."""


class ProposerMalformedOutput(ProposerError):
    """The response carried no extractable structured payload."""


class ProposerSchemaViolation(ProposerError):
    """The payload was rejected by the production Proposal schema.

    This is a MODEL failure, not infrastructure. The pipeline maps it to
    MODEL_OUTPUT_SCHEMA_INVALID so benchmark reporting can separate parse
    failures from reasoning errors.
    """
