"""Object keys in the artifacts bucket (or the local blobs directory)."""


def clean_table(location: str) -> str:
    return f"data/clean/{location}.json"


def model(location: str, version: str) -> str:
    return f"models/{location}/{version}/model.json"


def metrics(location: str, version: str) -> str:
    return f"models/{location}/{version}/metrics.json"


def champion(location: str) -> str:
    return f"models/{location}/champion.json"


def candidate(location: str) -> str:
    return f"models/{location}/candidate.json"


def archive_prefix(location: str, version: str) -> str:
    return f"archive/{location}/{version}/"


def archive(location: str, version: str, generated_at: str) -> str:
    """Every forecast run is archived so accuracy can be scored against later actuals."""
    return archive_prefix(location, version) + generated_at.replace(":", "") + ".json"
