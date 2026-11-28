import json
import threading
from urllib.request import urlopen

import pytest

from src.server import make_server


@pytest.fixture
def base_url():
    server = make_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def test_serves_windows_over_http(base_url: str) -> None:
    with urlopen(f"{base_url}/windows?duration_hours=3&region=PJM") as response:
        assert response.status == 200
        assert response.headers["Access-Control-Allow-Origin"] == "*"
        data = json.load(response)
    assert data["region"] == "PJM"
    assert data["job"]["duration_hours"] == 3
