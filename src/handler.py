"""AWS Lambda entry point for the EcoShift API.

Serves ``GET /forecast`` and ``GET /windows`` from ``src/api.py``, for an API
Gateway HTTP API or a Lambda Function URL (payload format 2.0). The local
server in ``src/server.py`` calls this same function, so the dashboard gets
the same responses in development as once deployed.
"""

from __future__ import annotations

import json
from datetime import datetime

from src.api import DEFAULT_REGION, DEFAULT_TOP, ApiError, get_forecast, get_windows

# The data is public and read-only, so any site may call the API from a browser.
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Accept, Content-Type",
}


def lambda_handler(event: dict, context: object) -> dict:
    """Answer one HTTP request.

    Args:
        event: API Gateway HTTP API or Function URL event (payload format 2.0).
        context: Lambda context. Unused.

    Returns:
        A response with ``statusCode``, ``headers`` and a JSON ``body``: the API
        response, or ``{"error": message}`` with status 400, 404 or 405.
    """
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    if method == "OPTIONS":
        return _response(204, None)
    if method != "GET":
        return _response(405, {"error": f"{method} isn't supported; use GET"})
    path = event.get("rawPath", "")
    params = event.get("queryStringParameters") or {}
    try:
        if path == "/forecast":
            return _response(200, get_forecast(params.get("region", DEFAULT_REGION)))
        if path == "/windows":
            return _response(200, _windows(params))
    except ApiError as err:
        return _response(400, {"error": str(err)})
    return _response(404, {"error": f"no endpoint at {path!r}; use /forecast or /windows"})


def _windows(params: dict[str, str]) -> dict:
    deadline = params.get("deadline")
    return get_windows(
        duration_hours=_whole_number(params, "duration_hours"),
        deadline=_parse_deadline(deadline) if deadline else None,
        region=params.get("region", DEFAULT_REGION),
        top=_whole_number(params, "top", DEFAULT_TOP),
    )


def _whole_number(params: dict[str, str], name: str, default: int | None = None) -> int:
    text = params.get(name)
    if text is None:
        if default is None:
            raise ApiError(f"{name} is required")
        return default
    try:
        return int(text)
    except ValueError:
        raise ApiError(f"{name} must be a whole number, not {text!r}") from None


def _parse_deadline(text: str) -> datetime:
    try:
        deadline = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError(f"deadline {text!r} isn't an ISO 8601 datetime") from None
    if deadline.tzinfo is None:
        raise ApiError("deadline needs a timezone, like 2026-10-22T09:00:00Z")
    return deadline


def _response(status: int, payload: dict | None) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", **CORS_HEADERS},
        "body": "" if payload is None else json.dumps(payload),
    }
