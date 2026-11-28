"""Upload a trained price model so the pipeline can use it.

    python -m carbon.price.upload_model path/to/model.joblib [path/to/metrics.json]

Uses whichever store CARBON_STORE selects (set CARBON_STORE=aws, AWS credentials and
CARBON_ARTIFACTS_BUCKET to upload to the deployed stack). The model becomes the candidate; the
gate step decides whether it replaces the champion.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from carbon.common.store import get_store
from carbon.price.run import register_model


def main(argv: list[str]) -> int:
    if not argv or len(argv) > 2:
        print(__doc__)
        return 2
    model = Path(argv[0])
    metrics = json.loads(Path(argv[1]).read_text()) if len(argv) == 2 else None
    version = register_model(get_store(), model.read_bytes(), metrics)
    print(f"uploaded {model.name} as {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
