"""Meridian Core — a deliberately hostile stand-in for a legacy bank back-office application.

It exists so Glovebox can be exercised against the realities described in the brief:
framesets, table layouts, no ids or test ids, server-rendered forms, JavaScript confirm dialogs,
and — most importantly — injectable runtime faults (session expiry, permission denial, slow
loads, application errors, validation errors, interstitial notices).

All data is fictional. Credentials are fake. Nothing here talks to a real institution.
"""

from .app import create_app

__all__ = ["create_app"]
