"""carbon-windows: find the cheapest time (CAISO day-ahead price, $/MWh) to run a heavy job.

Output is a table by default and JSON with --json (for coding agents).

Exit codes:
  0  success
  2  usage error (bad arguments)
  3  API unreachable
  4  data returned, but the forecast is stale or the pipeline failed (see `warnings`)
  5  API returned an error (unsupported location, no forecast yet, ...)
"""

from __future__ import annotations

import json
import os
from typing import Optional

import httpx
import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help=__doc__, no_args_is_help=True, add_completion=False)
console = Console()

EXIT_UNREACHABLE, EXIT_STALE, EXIT_API_ERROR = 3, 4, 5
UNTRUSTED = {"forecast_stale", "pipeline_failed"}

LocationOpt = typer.Option(
    lambda: os.environ.get("CARBON_LOCATION", "demo-region"), "--location", "-l", help="Location id: a campus id (env CARBON_LOCATION). See `sites`."
)
JsonOpt = typer.Option(False, "--json", help="Print JSON instead of a table.")
AllowStaleOpt = typer.Option(False, "--allow-stale", help="Exit 0 even if the data is stale or the pipeline failed.")


def get_client() -> httpx.Client:
    return httpx.Client(base_url=os.environ.get("CARBON_API_URL", "http://localhost:8000"), timeout=10.0)


def _get(path: str, params: dict | None = None) -> dict:
    try:
        with get_client() as client:
            response = client.get(path, params={k: v for k, v in (params or {}).items() if v is not None})
    except httpx.TransportError as exc:
        typer.echo(f"error: cannot reach the API ({exc.__class__.__name__}). Set CARBON_API_URL.", err=True)
        raise typer.Exit(EXIT_UNREACHABLE) from None
    if response.status_code >= 400:
        try:
            detail = response.json().get("error") or response.json().get("detail")
        except ValueError:
            detail = response.text
        typer.echo(f"error: API returned {response.status_code}: {detail}", err=True)
        raise typer.Exit(EXIT_API_ERROR)
    return response.json()


def _finish(data: dict, allow_stale: bool) -> None:
    if UNTRUSTED & set(data.get("warnings", [])) and not allow_stale:
        typer.echo(f"warning: {', '.join(data['warnings'])} (exit {EXIT_STALE}; use --allow-stale to ignore)", err=True)
        raise typer.Exit(EXIT_STALE)


def _short(ts: str) -> str:
    return ts[:16].replace("T", " ")


def _hours(minutes: int) -> str:
    return "now" if minutes == 0 else f"{minutes / 60:g}h"


@app.command()
def best(
    duration: int = typer.Option(..., "--duration", "-d", min=1, help="Job length in hours."),
    max_wait: Optional[str] = typer.Option(None, "--max-wait", "-w", help="Longest delay you accept, e.g. 3h or 1d."),
    deadline: Optional[str] = typer.Option(None, "--deadline", help="ISO time the job must finish by."),
    location: str = LocationOpt,
    top: int = typer.Option(3, "--top", min=1, max=5),
    kw: Optional[float] = typer.Option(None, "--kw", min=0.001, help="Constant load in kW (default 8)."),
    node: Optional[str] = typer.Option(None, "--node", help="Price at this pricing node instead of the nearest."),
    as_json: bool = JsonOpt,
    allow_stale: bool = AllowStaleOpt,
):
    """Best windows to run a job of --duration hours."""
    data = _get(
        "/v1/windows",
        {
            "location": location, "node": node, "duration_hours": duration, "max_wait": max_wait,
            "deadline": deadline, "top": top, "kw": kw,
        },
    )
    if as_json:
        typer.echo(json.dumps(data))
    else:
        b = data["best"]
        if data["recommendation"] == "delay":
            console.print(f"[bold]Delay {_hours(b['wait_minutes'])}[/bold]: saves ${b['savings_usd']:.2f} vs running now")
        else:
            console.print("[bold]Run now[/bold]: waiting would not save enough to matter")
        table = Table("#", "Start (UTC)", "End (UTC)", "Wait", "$/MWh", "Cost", "Saves")
        for i, w in enumerate([b, *data["alternatives"]], 1):
            table.add_row(
                str(i), _short(w["start"]), _short(w["end"]), _hours(w["wait_minutes"]), f"{w['avg']}",
                f"${w['cost_usd']:.2f}", f"${w['savings_usd']:.2f}",
            )
        console.print(table)
        console.print(f"Job: {data['request']['kw']:g} kW for {data['request']['duration_hours']} h. Run now: ${data['run_now_cost_usd']:.2f}")
        console.print(f"Forecast {data['model_version']} ({data['data_source']}) generated {data['generated_at']}")
        for w in data["warnings"]:
            console.print(f"[yellow]warning:[/yellow] {w}")
    _finish(data, allow_stale)


@app.command()
def forecast(
    hours: Optional[int] = typer.Option(None, "--hours", min=1, max=240, help="Limit to the next N hours."),
    location: str = LocationOpt,
    node: Optional[str] = typer.Option(None, "--node", help="Price at this pricing node instead of the nearest."),
    as_json: bool = JsonOpt,
    allow_stale: bool = AllowStaleOpt,
):
    """Hourly price: published day-ahead prices first, then the model's forecast."""
    data = _get("/v1/forecast", {"location": location, "node": node, "hours": hours})
    if as_json:
        typer.echo(json.dumps(data))
    else:
        table = Table("Hour (UTC)", "$/MWh", "Kind")
        for r in data["rows"]:
            table.add_row(_short(r["ts"]), f"{r['price']}", r.get("kind", ""))
        console.print(table)
        for w in data["warnings"]:
            console.print(f"[yellow]warning:[/yellow] {w}")
    _finish(data, allow_stale)


@app.command()
def sites(as_json: bool = JsonOpt):
    """Places that can be forecast (datacenter campuses for the price model)."""
    data = _get("/v1/sites")
    if as_json:
        typer.echo(json.dumps(data))
    else:
        table = Table("Location id", "Name", "City")
        for s in data["sites"]:
            table.add_row(s["location"], s["name"], s["city"])
        console.print(table)


@app.command()
def status(as_json: bool = JsonOpt, allow_stale: bool = AllowStaleOpt):
    """Pipeline status and forecast freshness."""
    data = _get("/v1/health")
    if as_json:
        typer.echo(json.dumps(data))
    else:
        console.print(f"Status: [bold]{data['status']}[/bold]   forecast age: {data['forecast_age_hours']}h")
        for w in data["warnings"]:
            console.print(f"[yellow]warning:[/yellow] {w}")
    if data["status"] == "no_data":
        typer.echo("error: no forecast has been generated yet", err=True)
        raise typer.Exit(EXIT_API_ERROR)
    _finish(data, allow_stale)


if __name__ == "__main__":
    app()
