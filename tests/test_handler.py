import json
from datetime import UTC, datetime, timedelta

import pytest

from src.handler import lambda_handler


def request(path: str, method: str = "GET", **params: str) -> dict:
    event = {
        "rawPath": path,
        "queryStringParameters": params or None,
        "requestContext": {"http": {"method": method}},
    }
    return lambda_handler(event, None)


def body(response: dict) -> dict:
    return json.loads(response["body"])


def test_forecast_returns_48_hours() -> None:
    response = request("/forecast", region="ERCO")
    assert response["statusCode"] == 200
    assert body(response)["region"] == "ERCO"
    assert len(body(response)["points"]) == 48


def test_forecast_defaults_to_ciso() -> None:
    assert body(request("/forecast"))["region"] == "CISO"


def test_windows_returns_ranked_windows() -> None:
    response = request("/windows", duration_hours="4", top="2")
    assert response["statusCode"] == 200
    data = body(response)
    assert data["job"]["duration_hours"] == 4
    assert [w["rank"] for w in data["windows"]] == [1, 2]


def test_windows_accepts_browser_deadline() -> None:
    # The dashboard sends Date.toISOString(): milliseconds and a Z suffix.
    deadline = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(hours=12)
    text = deadline.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    data = body(request("/windows", duration_hours="2", deadline=text))
    assert datetime.fromisoformat(data["job"]["deadline"]) == deadline


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"duration_hours": "four"},
        {"duration_hours": "0"},
        {"duration_hours": "2", "region": "NOPE"},
        {"duration_hours": "2", "deadline": "2026-10-22T09:00"},  # no timezone
        {"duration_hours": "2", "deadline": "tomorrow"},
        {"duration_hours": "2", "top": "x"},
    ],
)
def test_bad_windows_request_is_400(params: dict[str, str]) -> None:
    response = request("/windows", **params)
    assert response["statusCode"] == 400
    assert body(response)["error"]


def test_unknown_path_is_404() -> None:
    assert request("/nope")["statusCode"] == 404


def test_post_is_405() -> None:
    assert request("/windows", method="POST")["statusCode"] == 405


def test_preflight_is_allowed() -> None:
    response = request("/windows", method="OPTIONS")
    assert response["statusCode"] == 204
    assert "GET" in response["headers"]["Access-Control-Allow-Methods"]


def test_every_response_allows_cross_origin_calls() -> None:
    for response in (request("/forecast"), request("/windows"), request("/nope")):
        assert response["headers"]["Access-Control-Allow-Origin"] == "*"
        assert response["headers"]["Content-Type"] == "application/json"
