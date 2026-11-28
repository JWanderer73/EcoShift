.PHONY: install test seed api web fixtures

install:
	pip install -e ".[cli,price,dev]"

test:
	pytest -q

seed:  ## run the whole pipeline locally (stub data) to create forecasts
	python -m carbon.jobs.pipeline

api:  ## http://localhost:8000/docs
	uvicorn carbon.api.main:app --reload

fixtures:  ## regenerate API response fixtures from the real code
	python scripts/make_fixtures.py

web:  ## Next.js UI at http://localhost:3000 (start the API first)
	cd frontend && npm install && NEXT_PUBLIC_ECOSHIFT_API_MODE=carbon-v1 API_PROXY_URL=http://localhost:8000 npm run dev
