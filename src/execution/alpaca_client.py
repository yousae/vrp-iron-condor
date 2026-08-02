"""
Alpaca Trading API integration for paper and (later, if Phase 6 passes)
live execution.

Reads credentials from environment variables -- see .env.example.
NEVER hardcode API keys in this file or commit a filled-in .env.
"""

import os


def get_client(paper: bool = True):
    """Return an authenticated Alpaca trading client.

    TODO: use the alpaca-py SDK. Base URL should switch between paper
    and live per the `paper` flag; default to paper always.

    Expects ALPACA_API_KEY and ALPACA_SECRET_KEY in the environment
    (via .env / python-dotenv).
    """
    api_key = os.environ.get("ALPACA_API_KEY")
    secret_key = os.environ.get("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        raise RuntimeError("Alpaca API credentials not found in environment.")
    raise NotImplementedError


def get_option_chain(underlying: str, expiration: str):
    """Fetch the current option chain (strikes, greeks, IV) for the
    given underlying and expiration.

    TODO: implement via alpaca-py's options data endpoint.
    """
    raise NotImplementedError


def place_iron_condor(
    client,
    short_put_symbol: str,
    long_put_symbol: str,
    short_call_symbol: str,
    long_call_symbol: str,
    quantity: int,
):
    """Submit a 4-leg iron condor as a single multi-leg order.

    TODO: implement via alpaca-py multi-leg order support. Confirm order
    details in chat before ever calling this against a live (non-paper)
    account -- this is a standing rule, not a suggestion.
    """
    raise NotImplementedError
