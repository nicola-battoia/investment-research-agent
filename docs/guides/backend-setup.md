# Backend setup

The existing backend is a FastAPI service. Do not re-scaffold it or run
`alembic init`; its dependencies, package and migrations are already checked in.

## 1. Prepare dependencies and settings

Install Python 3.12+ and uv. From the repository root:

```bash
cd backend
uv sync --locked
cp -n .env.example .env
```

Fill in the required values described in [configuration](../configuration.md).
Use a [Supabase development project](supabase-setup.md) and
[Azure Foundry deployments](azure-foundry-setup.md). A copied placeholder file
is enough to describe the shape of configuration, but cannot authenticate to services.

`uv sync` installs `app/` as an editable package. Run operator modules from
`backend/`; `ingestion/` and `evaluation/` are not included in the application wheel.

## 2. Apply the schema and start the API

Confirm that `DATABASE_URL` targets the intended database, then:

```bash
uv run --locked alembic upgrade head
uv run --locked uvicorn app.main:app --reload
```

The database URL must use `postgresql+psycopg://` with a direct or session
connection. See [Supabase setup](supabase-setup.md) for pooler details.

Open [health](http://localhost:8000/health) and [API docs](http://localhost:8000/docs).
The health route checks process availability, not Azure/Supabase connectivity.
Running `python app/main.py` imports the app but does not start Uvicorn.

## 3. Check changes

```bash
uv run --locked pytest -m "not integration"
uv run --locked ruff check app tests ingestion evaluation playground
uv run --locked ruff format --check app tests ingestion evaluation playground
```

Tests need valid settings at collection time, but the selected suite uses mocked
service boundaries. Keep Azure tracing disabled for ordinary offline tests.
See [evaluation](../../backend/evaluation/README.md) for deliberate live tests.

## Schema changes

Update the relevant SQLAlchemy model in `app/database/`, then generate and review:

```bash
uv run --locked alembic revision --autogenerate -m "describe the schema change"
uv run --locked alembic heads
uv run --locked alembic upgrade head --sql
```

The last command renders the entire base-to-head SQL chain offline. Use
`alembic upgrade <known-revision>:head --sql` to render a specific range.
It cannot inspect which migrations the live database still needs.

Review RLS, grants, functions, generated text-search columns, pgvector dimensions
and indexes explicitly. Commit model and migration changes together. Apply reviewed
migrations with `uv run --locked alembic upgrade head`; Railway uses the equivalent
command in its pre-deploy container.

## IPython and corpus work

Select `backend/.venv/bin/python` as the editor's Python/IPython environment.
Optionally register a named kernel:

```bash
uv run --locked python -m ipykernel install --user \
  --name document-copilot-backend --display-name "Document Copilot Backend"
```

Run the playground's `# %%` cells in that kernel, not as ordinary Python scripts.
See [evaluation](../../backend/evaluation/README.md) for credentials and side effects.
Use [data](../../data/README.md) and [ingestion](../../backend/ingestion/README.md)
for downloading and preparing filings.
