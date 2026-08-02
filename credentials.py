"""The S3 secret a build writes through, and how to keep it alive.

Queria hands a build a *way to get* credentials rather than the values: an AWS
profile naming ``queria auth credential-process``, which DuckDB's credential
chain runs. The build then creates one secret and writes through it.

**DuckDB resolves that chain once, when the secret is created.** It does not
consult the ``Expiration`` the process returns. Measured against R2 on
2026-07-31, with a process that returned working keys but claimed a twenty
second expiry:

    one query reading 1.8 GB over forty seconds  -> process ran once
    two queries thirty seconds apart, one conn   -> process ran once
    the same, re-issuing the secret each round   -> process ran every round

So ``REFRESH auto`` is not a timer. The chain runs again when the secret is
created again, and a build that outlives one credential has to do that itself
-- otherwise storage starts rejecting its requests the moment the credential
expires (403, ``SignatureDoesNotMatch``), and the build dies mid-flight.

Call :meth:`Secret.refresh_if_due` where the build already has a seam: between
batches, between flushes, at the top of a per-item loop. The cost is one
subprocess and one mint, so a seam every few seconds is fine to call from --
the interval decides how often it actually fires, not the call site.

**A seam is required.** A single statement that runs past the expiry cannot be
rescued from here; nothing gets to run between its requests. That case needs
the statement split, or a longer TTL on the account.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Protocol

#: How long a credential lives by default. The account can be given longer
#: (``user_profiles.credential_ttl_seconds``), so this is the floor, not the
#: actual: refreshing on a schedule that holds for the floor holds for any of
#: them.
DEFAULT_TTL = timedelta(minutes=15)

#: How often to re-issue. Comfortably inside DEFAULT_TTL so the replacement
#: lands well before the credential it replaces expires, and far enough apart
#: that a tight loop does not mint on every pass.
DEFAULT_INTERVAL = timedelta(minutes=10)


class Connection(Protocol):
    """The part of a DuckDB connection this needs."""

    def execute(self, query: str, parameters: object = ...) -> object: ...


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Secret:
    """One build's S3 secret, re-issued before it expires.

    The statement is the same one every dataset used to carry inline. Keeping
    it here means the shape of the secret -- the chain, the endpoint, whether
    TLS is on -- is decided once.
    """

    #: The secret's name. Naming it makes CREATE OR REPLACE replace *this* one
    #: rather than leaving a second unnamed secret behind on every refresh.
    NAME = "queria_build"

    def __init__(
        self,
        conn: Connection,
        *,
        interval: timedelta = DEFAULT_INTERVAL,
        clock=_now,
    ) -> None:
        self._conn = conn
        self._interval = interval
        self._clock = clock
        self._issued_at: datetime | None = None

    @staticmethod
    def needed() -> bool:
        """Whether the build writes somewhere that needs signing at all.

        A build against a local path has no secret to keep alive.
        """
        return os.environ.get("QUERIA_DATA_URL", "").startswith("s3://")

    def install(self) -> None:
        """Create the secret. Call once, where the connection is set up."""
        self._issue()

    def refresh(self) -> None:
        """Re-issue now, whatever the interval says."""
        self._issue()

    def refresh_if_due(self) -> None:
        """Re-issue if the interval has passed. Cheap to call often."""
        if self._issued_at is not None:
            if self._clock() - self._issued_at < self._interval:
                return
        self._issue()

    def _issue(self) -> None:
        # USE_SSL cannot be a parameter: DuckDB takes it as a literal in the
        # option list, unlike ENDPOINT and REGION.
        use_ssl = "false" if os.environ.get("QUERIA_S3_USE_SSL") == "false" else "true"
        self._conn.execute(
            f"CREATE OR REPLACE SECRET {self.NAME} (TYPE s3, "
            "PROVIDER credential_chain, CHAIN 'process', REFRESH auto, "
            f"ENDPOINT ?, URL_STYLE 'path', REGION ?, USE_SSL {use_ssl})",
            [
                os.environ["QUERIA_S3_ENDPOINT_HOST"],
                os.environ.get("QUERIA_S3_REGION", "auto"),
            ],
        )
        self._issued_at = self._clock()
