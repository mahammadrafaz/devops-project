"""Helpers that always derive tenant scope from the signed-in user."""

from flask_login import current_user


def current_business():
    """Return the business belonging to the authenticated user, or None."""
    if not current_user.is_authenticated:
        return None
    return current_user.business


def current_business_id():
    """Return the authenticated user's tenant id; never accept a browser id."""
    if not current_user.is_authenticated:
        return None
    return current_user.business_id
