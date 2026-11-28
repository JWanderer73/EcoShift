"""Runs the whole pipeline and API against fake AWS (moto), so the AWS code path is exercised."""

import boto3
import pytest

pytest.importorskip("moto")
from moto import mock_aws  # noqa: E402

from carbon.common.store import get_store  # noqa: E402


@pytest.fixture
def aws(monkeypatch):
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(k, "test")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("CARBON_STORE", "aws")
    monkeypatch.setenv("CARBON_ARTIFACTS_BUCKET", "test-artifacts")
    with mock_aws():
        ddb = boto3.client("dynamodb")
        ddb.create_table(
            TableName="carbon-windows-forecasts",
            AttributeDefinitions=[{"AttributeName": "location", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "location", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            BillingMode="PAY_PER_REQUEST",
        )
        ddb.create_table(
            TableName="carbon-windows-status",
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
            BillingMode="PAY_PER_REQUEST",
        )
        boto3.client("s3").create_bucket(Bucket="test-artifacts")
        yield


def test_pipeline_and_api_work_against_aws_services(aws, client):
    from carbon.jobs import accuracy, pipeline

    pipeline.run()
    status = get_store().get_status()
    assert status["last_run_status"] == "success"

    body = client.get("/v1/windows", params={"duration_hours": 4, "max_wait": "1d"}).json()
    assert body["recommendation"] in {"run_now", "delay"} and body["warnings"] == []
    assert len(client.get("/v1/forecast").json()["rows"]) == 48
    assert client.get("/v1/health").json()["status"] == "ok"

    # a failure record written the way Step Functions writes it is picked up by the API
    boto3.client("dynamodb").update_item(
        TableName="carbon-windows-status",
        Key={"pk": {"S": "pipeline"}},
        UpdateExpression="SET last_run_status = :s, last_error = :e",
        ExpressionAttributeValues={":s": {"S": "failed"}, ":e": {"S": "{}"}},
    )
    assert "pipeline_failed" in client.get("/v1/forecast").json()["warnings"]

    # archives are listable in S3 and the accuracy job can publish a CloudWatch metric
    assert get_store().list_blobs("archive/demo-region/")
    get_store().put_metric("RollingMAE", 12.5, {"Location": "demo-region"})
    assert accuracy.run() is not None
