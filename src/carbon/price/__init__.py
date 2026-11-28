"""The delivered CAISO day-ahead price model, wired into the pipeline.

The model itself lives untouched in `price_windows/` (see its README). This package is the
glue: it finds the campuses, refreshes the price history, runs the model and shapes its output
for the store and the API. Training happens offline; the trained file is uploaded with
`python -m carbon.price.upload_model`.
"""
