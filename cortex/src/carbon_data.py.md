src/carbon_data.py

# carbon_data.py

carbon_data.py exports repo_root, cache_path, carbon_intensity, model_frame, load_hourly_panel, and load_model_frame.

<!-- cortex-file -->

## repo_root

No parameters go in. Sets here to Path.cwd of ).resolve(. Loops while candidate / requirements.txt, it continues. Gives here back.

<!-- cortex-logic -->

## cache_path

No parameters go in. Gives repo_root() / data / processed / hourly_model_panel.csv back.

<!-- cortex-logic -->

## carbon_intensity

fuels goes in. Sets frame to the result of fuels.copy.

<!-- cortex-logic -->

## model_frame

panel goes in. It handles model frame.

<!-- cortex-logic -->

## load_hourly_panel

refresh goes in. Sets path to the result of cache_path.

<!-- cortex-logic -->

## load_model_frame

refresh goes in. Gives model_frame of load_hourly_panel of refresh=refresh back.

<!-- cortex-logic -->

## _fetch_hourly_panel

No parameters go in. If EIA_API_KEY, it continues.

<!-- cortex-logic -->

## _eia_pages

route and params go in. Sets def _eia_pages(route: str, params: list) -> pd.DataFrame: rows: list[dict] to an empty list.

<!-- cortex-logic -->

## _weather

No parameters go in. Sets def _weather() -> pd.DataFrame: frames to an empty list.

<!-- cortex-logic -->

## _get_json

url and timeout go in. It gives payload back unchanged.

<!-- cortex-logic -->

<!-- cortex-source-hash:fad583cba85d0dd2d4f7418bbdb2f0d5a5bc1f82f0913a2854bfd7c7972621ce -->
