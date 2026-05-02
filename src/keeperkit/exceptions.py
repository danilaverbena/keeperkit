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
