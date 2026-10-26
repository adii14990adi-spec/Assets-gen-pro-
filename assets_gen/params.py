"""Coercion helpers for generator parameters.

Parameters arrive from JSON bodies or query strings, so everything is
normalised here and out-of-range values raise :class:`ParamError`, which the
API surfaces as a 422 response.
"""

from __future__ import annotations

from collections.abc import Mapping

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}


class ParamError(ValueError):
    """Raised when a generator parameter cannot be interpreted."""


def as_int(
    params: Mapping[str, object],
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = params.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ParamError(f"'{name}' must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ParamError(f"'{name}' must be between {minimum} and {maximum}")
    return value


def as_choice(
    params: Mapping[str, object],
    name: str,
    default: str,
    choices: tuple[str, ...],
) -> str:
    raw = params.get(name)
    if raw is None or raw == "":
        return default
    value = str(raw).strip().lower()
    if value not in choices:
        raise ParamError(f"'{name}' must be one of: {', '.join(choices)}")
    return value


def as_bool(params: Mapping[str, object], name: str, default: bool) -> bool:
    raw = params.get(name)
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    value = str(raw).strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ParamError(f"'{name}' must be a boolean")


def as_text(
    params: Mapping[str, object],
    name: str,
    default: str = "",
    max_length: int = 16,
) -> str:
    raw = params.get(name)
    if raw is None:
        return default
    value = " ".join(str(raw).split())
    if len(value) > max_length:
        raise ParamError(f"'{name}' must be at most {max_length} characters")
    return value
