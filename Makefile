.PHONY: install test seed api dashboard fixtures

install:
	pip install -e ".[cli,dashboard,dev]"

test:
	pytest -q

seed:  ## run the whole pipeline locally (stub data) to create forecasts
	python -m carbon.jobs.pipeline

api:  ## http://localhost:8000/docs
	uvicorn carbon.api.main:app --reload

dashboard:  ## http://localhost:8501 (start the API first)
	streamlit run dashboard/app.py

fixtures:  ## regenerate API response fixtures from the real code
	python scripts/make_fixtures.py
