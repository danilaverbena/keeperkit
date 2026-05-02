"""Exceptions raised by the KeeperKit client."""

from __future__ import annotations


class KeeperHubAPIError(RuntimeError):
    """Base class for KeeperHub API failures."""

    def __init__(self, message: str, *, status_code: int | None = None,
                 payload: object | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class KeeperHubAuthError(KeeperHubAPIError):
    """Raised on 401/403 — invalid or missing API key."""


class KeeperHubNotFoundError(KeeperHubAPIError):
    """Raised on 404 — workflow / execution / integration not found."""


class KeeperHubValidationError(KeeperHubAPIError):
    """Raised on 400 — invalid parameters (bad node config, missing field, etc.)."""


class KeeperHubPaymentRequired(KeeperHubAPIError):
    """Raised on 402 — the workflow is paid and an x402 payment is required.

    KeeperHub paid workflows respond with HTTP 402, an
    ``x-payment-requirements`` header (base64-encoded JSON describing the
    accepted x402 payment schemes), and a ``www-authenticate: Payment …``
    challenge. The decoded descriptor is exposed on :attr:`x402` so callers
    can route through their x402 settlement client (agentcash / openclaw /
    a custom signer) and replay the request with an ``X-Payment`` header.
    """

    def __init__(
        self,
        message: str,
        *,
        x402: dict | None = None,
        www_authenticate: str | None = None,
        payload: object | None = None,
    ) -> None:
        super().__init__(message, status_code=402, payload=payload)
        self.x402 = x402 or {}
        self.www_authenticate = www_authenticate

    @property
    def amount_usdc(self) -> str | None:
        """Convenience: cost (in atomic USDC, 6 decimals) for the cheapest accept."""
        accepts = (self.x402 or {}).get("accepts") or []
        if not accepts:
            return None
        return accepts[0].get("amount")
