"""ID map, IRI minting and the namespace lock (spec 3.4, 5.4).

Filled by task B4. The ID map — not the minting formula — is authoritative, which is
what lets codes, minting rules and compiler versions change without breaking identity.
IRIs are opaque and permanent: never deleted, never reused.
"""

from __future__ import annotations
