# CLAUDE.md

Guidance for Claude Code when working in the EcoShift repo.

## Project overview

**EcoShift (Advanced)**

Using automated MLOps pipelines and serverless infrastructure, the team will build an API that identifies the lowest-emission time windows for heavy workloads using historical energy data and weather forecasts. These insights will be displayed through an interactive dashboard and a CLI tool usable by coding agents.

- **Deliverables:** automated ML forecasting pipeline, serverless API architecture, interactive web UI, Python CLI, LLM agent skill, GitHub repository, architecture diagram, final presentation.
- **Learning goals:** MLOps, AWS cloud services/architecture, LLM skill building, CLI development.
- **Workload:** 6–8 hours/week.
- **Prerequisites:** DSC 80 (or equivalent Python library and ML knowledge), some experience with cloud, Git/GitHub, experience with coding agents.
- **Preferred experience (one or more):** REST APIs, strong grasp of cloud fundamentals and IAM, MLOps, CLI development tools, agent skill creation.

## Design doc spec

Status: in planning. Each decision should briefly justify its benefit and cost (more detail to come).

### ML pipeline

**Metrics**
- Accuracy: average error of the forecast (MAE).
- Usefulness: how much CO₂ you save by waiting vs. running now.
- Compute: training time and API response time.

**Datasets**
- EIA-930 Hourly Grid Monitor: free hourly data on what power plants are running.
- Open-Meteo: free weather API for wind, sun, and temperature.
- EPA eGRID emission factors.

**When to bring in more datasets**
- If errors are high in only one region, add data from neighboring regions.
- If errors are high during solar ramp hours, we can … _(unfinished)_

**Merge and validation**

```
EIA-930 grid data ──► check for missing/bad values ──┐
                                                      ├──► join by hour ──► clean table (S3) ──► train model
Open-Meteo weather ──► check for missing/bad values ──┘
```

- Each dataset is checked automatically before merging: filter impossible values and duplicate timestamps.
- Model validation trains on older data and tests on newer data. Never use a random split, which lets the model see the future.

**Retraining parameters** (most likely to change in future)
- Retrain frequency
- Training history
- Forecast length

### Cloud architecture

- Resilient serving: the model saves predictions every hour and the API just reads them, so if the model breaks the API still works.
- Load balancer, AZs: not needed; serverless services already run in multiple data centers.
- Outputs: the API returns the best time to run a job. The dashboard shows them on a chart, and the CLI prints them in the terminal.

### UI / CLI

**Displaying output**
- The dashboard shows a line chart of predicted carbon intensity over the next 48 hours, with the best time windows highlighted.
- Next to the chart is a small form: enter how long the job is and when it must finish, and get the top 3 windows plus % CO₂ saved.
- The CLI prints a simple table by default, and JSON so coding agents can read it.

**Dashboard frontend** (decided: React, same setup as Pulp)
- Next.js (App Router) + React + TypeScript, lives in `frontend/`.
- Tailwind CSS with shadcn-style components and lucide icons.
- ESLint for linting, Vitest for unit tests, Playwright for end-to-end tests.
- Hosted on Vercel.
- Runs on labeled sample data until `NEXT_PUBLIC_ECOSHIFT_API_URL` is set. `frontend/README.md` has the commands and the API contract (same JSON as `carbon windows --json`, plus a `/forecast` endpoint for the chart).

**CLI**
- Built with Typer, a simple Python library for building commands.
- Ship a short instruction file telling coding agents when to run `carbon windows` (for example, before long training jobs) and how to read the result.

## Tentative architecture plan

Two paths sharing one storage layer:
- **Batch path (scheduled):** EventBridge triggers Step Functions, which runs one Lambda to ingest and validate EIA-930 and Open-Meteo data, then a second Lambda (container image) to train and predict. Clean data and model files go to S3, and hourly forecasts go to DynamoDB.
- **Serving path (per request):** the dashboard or CLI calls API Gateway, which invokes a Lambda that reads forecasts from DynamoDB. It finds the lowest-emission windows before the deadline and returns them with the % CO₂ saved versus running now.
- **No ML at request time:** if the model or pipeline fails, the API keeps serving the last good forecast.

### Free-tier choices

- Training runs in a Lambda container image. If it outgrows Lambda's 15-minute limit, use a scheduled GitHub Actions job as the fallback. Skip Fargate and SageMaker.
- The dashboard is hosted outside AWS on Vercel.
- DynamoDB uses small provisioned capacity to fit the always-free allowance. Verify this on the Free Tier page.
- API Gateway stays, with its small cost covered by credits. The zero-credit alternative is a Lambda Function URL with a shared-secret header and a low reserved-concurrency cap.
- Avoid NAT gateways, load balancers, EC2, RDS, and always-on containers.

### Resilience

- API Gateway, Lambda, DynamoDB, and S3 are multi-AZ already, so no load balancer is needed.
- Every response carries `generated_at` and a `stale` flag.
- Bad data is quarantined: the pipeline keeps the previous clean table and raises an alarm.
- A promotion gate only publishes a new model if its backtest MAE is within tolerance of the current one.
- Step Functions retries external data pulls with backoff.
- An hourly job compares past forecasts with actuals and publishes rolling MAE to CloudWatch, which drives retraining. Stay within the free metric and alarm counts.

### Security and deployment

- Separate least-privilege IAM roles (the API role is DynamoDB read-only), private S3, and secrets in SSM Parameter Store and GitHub Secrets.
- The repo is public: never commit the EIA key or AWS credentials, and turn on GitHub secret scanning.
- Infrastructure in CDK (Python), deployed from GitHub Actions via OIDC with no long-lived keys. Everything goes through CDK so `cdk destroy` cleans the account at the end.
- The account owner turns on root MFA, creates individual IAM users for teammates, and keeps the root login out of chat and the repo.

### Model lifecycle

- A fixed train / predict interface, with the model chosen in a config file.
- Versioned models in S3 with metadata (features, date range, per-horizon MAE, regret vs. baselines).
- Challenger models can run in shadow mode, writing forecasts under their own version tag without being served.
- Modelers work locally on a cached data snapshot, with a short backtest in CI on model pull requests.
- Retraining parameters live in the config: refresh cadence (default every 3 hours), retrain frequency (default weekly), training history length, forecast horizon (48 hours), and promotion tolerance.

### Remaining questions

- Which regions and how many years of history will the model use? This sets storage needs and training cost, and decides whether training fits in Lambda or needs the GitHub Actions fallback.
- Should the API use API Gateway (more AWS to learn, small credit use) or a Lambda Function URL (zero credits, less built-in protection)?
- What refresh cadence does the data team settle on? The default of every 3 hours can change in the config without altering the architecture.
