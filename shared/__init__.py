"""Shared, hardened primitives used by all three portfolio bots.

Single source of truth for broker HTTP resilience, order idempotency, and fill
confirmation so P1/P2/P3 cannot drift apart on the money path.
"""
