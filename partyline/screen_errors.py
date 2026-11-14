"""Screen route failures that always carry words a person can read."""

from fastapi import HTTPException


class HelperTimeout(TimeoutError):
    """The paired computer did not answer a request within its deadline."""


def screen_error(exc: Exception, subject: str = "the sharing computer") -> HTTPException:
    """409 for a refused request, 504 when the computer stayed silent; never an empty detail."""
    if isinstance(exc, TimeoutError):
        return HTTPException(504, str(exc) or f"{subject} did not answer in time; "
                                              "the helper may be busy or outdated")
    return HTTPException(409, str(exc) or f"{subject} could not complete the request")
