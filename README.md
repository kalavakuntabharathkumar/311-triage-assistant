# 311 Service Request Triage Assistant

AI-powered pipeline that ingests NYC 311 open data, classifies urgency with an LLM, and serves a real-time ops dashboard for municipal stakeholders.

## Architecture

```
NYC 311 API (Socrata) → Incremental ETL → SQLite → LLM Triage (GPT-3.5-turbo) → Enriched DB → Streamlit Dashboard
```

## Features

- **Incremental ETL**: Fetches new/updated 311 requests via paginated Socrata API, upserts idempotently into SQLite using `unique_key`.
- **LLM Triage**: Classifies each request with urgency (1-5), responsible department, and a plain-language summary using OpenAI GPT-3.5-turbo. Supports OpenAI Batch API for cost-effective bulk processing.
- **Streamlit Dashboard**: Interactive borough heatmaps, SLA breach trends, category drilldowns, and real-time filters.
- **Containerized Deployment**: Docker image runs daily batch job on AWS ECS Fargate; scheduled via EventBridge.

## Data Source

**NYC Open Data 311 Service Requests** – live, paginated, 25M+ records since 2010.
API endpoint: `https://data.cityofnewyork.us/resource/erm2-nwe9.json`

## Quick Start (Local)

```bash
# 1. Clone & install
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env with your OPENAI_API_KEY

# 3. Run initial ETL (fetches last 30 days)
python -m etl --days-back 30

# 4. Run triage on untriaged records
python -m triage --batch-size 100

# 5. Launch dashboard
streamlit run dashboard.py
```

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `OPENAI_API_KEY` | OpenAI API key for GPT-3.5-turbo | Yes |
| `DB_PATH` | SQLite database file (default: `data/311.db`) | No |
| `BATCH_API` | Use OpenAI Batch API (true/false, default: false) | No |
| `LOG_LEVEL` | Python logging level (default: INFO) | No |

## Docker

```bash
# Build
docker build -t 311-triage-assistant .

# Run ETL + triage once
docker run --env-file .env 311-triage-assistant python -m etl --days-back 1 && python -m triage

# Run dashboard (exposes port 8501)
docker run -p 8501:8501 --env-file .env 311-triage-assistant streamlit run dashboard.py --server.port=8501 --server.address=0.0.0.0
```

## AWS Fargate Deployment (Outline)

1. Push image to ECR: `docker push <account>.dkr.ecr.<region>.amazonaws.com/311-triage-assistant:latest`
2. Create ECS task definition (see `infra/task-def.json`) with:
   - CPU: 512, Memory: 1024
   - Environment variables from Secrets Manager (OPENAI_API_KEY)
   - Entrypoint: `python -m etl --days-back 1 && python -m triage --batch-size 500`
3. Schedule via EventBridge cron (e.g., `0 3 * * ? *` for 3 AM daily).

## Project Structure

```
├── etl.py              # Incremental extract/load from NYC 311 API
├── triage.py           # LLM classification & enrichment
├── dashboard.py        # Streamlit dashboard
├── main.py             # CLI entry point (orchestrates etl/triage)
├── models.py           # Pydantic models & DB schema
├── utils.py            # Shared helpers (HTTP retry, logging)
├── Dockerfile          # Multi-stage build
├── .env.example        # Template for environment variables
├── requirements.txt    # Python dependencies
└── infra/
    └── task-def.json   # ECS task definition template
```

## License

MIT
