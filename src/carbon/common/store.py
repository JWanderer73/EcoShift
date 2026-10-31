"""Storage backends.

`LocalStore` keeps everything as JSON files under CARBON_LOCAL_DIR, so the whole
system runs on a laptop with no AWS account. `AwsStore` uses DynamoDB (forecasts
and pipeline status), S3 (clean tables and the model registry) and CloudWatch
(metrics). Both expose the same interface; select with CARBON_STORE=local|aws.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from decimal import Decimal
from pathlib import Path

from carbon.config import Settings, get_settings

STATUS_PK = "pipeline"


class Store(ABC):
    # --- blobs: clean tables, models, pointers ---
    @abstractmethod
    def put_blob(self, key: str, data: bytes) -> None: ...

    @abstractmethod
    def get_blob(self, key: str) -> bytes | None: ...

    @abstractmethod
    def list_blobs(self, prefix: str) -> list[str]: ...

    def put_json(self, key: str, obj) -> None:
        self.put_blob(key, json.dumps(obj).encode())

    def get_json(self, key: str):
        data = self.get_blob(key)
        return None if data is None else json.loads(data)

    # --- forecasts: rows are {"ts", "intensity", "p10", "p90"} ---
    @abstractmethod
    def put_forecast(self, location: str, version: str, generated_at: str, rows: list[dict]) -> None: ...

    @abstractmethod
    def get_forecast(self, location: str, version: str) -> dict | None:
        """Return {"generated_at": str, "rows": [...]} or None."""

    # --- pipeline status record ---
    @abstractmethod
    def get_status(self) -> dict:
        """Return the status record, or {} if the pipeline has never run."""

    @abstractmethod
    def update_status(self, fields: dict) -> None:
        """Merge `fields` into the status record."""

    # --- metrics ---
    @abstractmethod
    def put_metric(self, name: str, value: float, dimensions: dict[str, str]) -> None: ...


class LocalStore(Store):
    def __init__(self, root: str):
        self.root = Path(root)

    def _path(self, *parts: str) -> Path:
        p = self.root.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def put_blob(self, key, data):
        self._path("blobs", key).write_bytes(data)

    def get_blob(self, key):
        p = self.root / "blobs" / key
        return p.read_bytes() if p.exists() else None

    def list_blobs(self, prefix):
        base = self.root / "blobs"
        if not base.exists():
            return []
        keys = (p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file())
        return sorted(k for k in keys if k.startswith(prefix))

    def put_forecast(self, location, version, generated_at, rows):
        self._path("forecasts", location, f"{version}.json").write_text(
            json.dumps({"generated_at": generated_at, "rows": rows})
        )

    def get_forecast(self, location, version):
        p = self.root / "forecasts" / location / f"{version}.json"
        return json.loads(p.read_text()) if p.exists() else None

    def get_status(self):
        p = self.root / "status.json"
        return json.loads(p.read_text()) if p.exists() else {}

    def update_status(self, fields):
        merged = {**self.get_status(), **fields}
        self._path("status.json").write_text(json.dumps(merged, indent=2))

    def put_metric(self, name, value, dimensions):
        with self._path("metrics.jsonl").open("a") as f:
            f.write(json.dumps({"name": name, "value": value, "dimensions": dimensions}) + "\n")


def _to_ddb(obj):
    return json.loads(json.dumps(obj), parse_float=Decimal)


def _from_ddb(obj):
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    if isinstance(obj, dict):
        return {k: _from_ddb(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_from_ddb(v) for v in obj]
    return obj


class AwsStore(Store):
    def __init__(self, settings: Settings):
        import boto3

        self.settings = settings
        self.ddb = boto3.resource("dynamodb")
        self.forecasts = self.ddb.Table(settings.forecasts_table)
        self.status = self.ddb.Table(settings.status_table)
        self.s3 = boto3.client("s3")
        self.cloudwatch = boto3.client("cloudwatch")

    def put_blob(self, key, data):
        self.s3.put_object(Bucket=self.settings.artifacts_bucket, Key=key, Body=data)

    def get_blob(self, key):
        try:
            obj = self.s3.get_object(Bucket=self.settings.artifacts_bucket, Key=key)
        except self.s3.exceptions.NoSuchKey:
            return None
        return obj["Body"].read()

    def list_blobs(self, prefix):
        keys: list[str] = []
        paginator = self.s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.settings.artifacts_bucket, Prefix=prefix):
            keys.extend(obj["Key"] for obj in page.get("Contents", []))
        return sorted(keys)

    def put_forecast(self, location, version, generated_at, rows):
        with self.forecasts.batch_writer() as batch:
            for row in rows:
                batch.put_item(
                    Item=_to_ddb(
                        {
                            "location": location,
                            "sk": f"{version}#{row['ts']}",
                            "model_version": version,
                            "generated_at": generated_at,
                            **row,
                        }
                    )
                )

    def get_forecast(self, location, version):
        from boto3.dynamodb.conditions import Key

        items: list[dict] = []
        kwargs = {
            "KeyConditionExpression": Key("location").eq(location) & Key("sk").begins_with(f"{version}#")
        }
        while True:
            resp = self.forecasts.query(**kwargs)
            items.extend(resp["Items"])
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        if not items:
            return None
        items = [_from_ddb(i) for i in items]
        rows = [{k: i[k] for k in ("ts", "intensity", "p10", "p90")} for i in items]
        return {"generated_at": items[0]["generated_at"], "rows": sorted(rows, key=lambda r: r["ts"])}

    def get_status(self):
        item = self.status.get_item(Key={"pk": STATUS_PK}).get("Item")
        if not item:
            return {}
        item = _from_ddb(item)
        item.pop("pk", None)
        return item

    def update_status(self, fields):
        merged = {**self.get_status(), **fields}
        self.status.put_item(Item=_to_ddb({"pk": STATUS_PK, **merged}))

    def put_metric(self, name, value, dimensions):
        self.cloudwatch.put_metric_data(
            Namespace="Carbon",
            MetricData=[
                {
                    "MetricName": name,
                    "Dimensions": [{"Name": k, "Value": v} for k, v in dimensions.items()],
                    "Value": float(value),
                }
            ],
        )


def get_store() -> Store:
    settings = get_settings()
    if settings.store == "aws":
        return AwsStore(settings)
    if settings.store == "local":
        return LocalStore(settings.local_dir)
    raise ValueError(f"Unknown CARBON_STORE '{settings.store}' (use 'local' or 'aws')")
