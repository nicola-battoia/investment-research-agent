# Documentation

Use the service READMEs for daily development, guides for setup and operation, and
the architecture/workflow documents to follow the implementation.

## Set up and operate

| Task | Read |
| --- | --- |
| Start both services | [Repository README](../README.md) |
| Configure credentials, models, budgets and tracing | [Configuration](configuration.md) |
| Prepare Supabase and private-pilot accounts | [Supabase setup](guides/supabase-setup.md) |
| Run the API, migrations and checks | [Backend setup](guides/backend-setup.md) and [backend README](../backend/README.md) |
| Run the SPA and verify user flows | [Frontend setup](guides/frontend-setup.md) and [frontend README](../frontend/README.md) |
| Configure Azure model deployments and inspect telemetry | [Azure Foundry](guides/azure-foundry-setup.md) |
| Download and ingest filings | [Data](../data/README.md) and [ingestion](../backend/ingestion/README.md) |
| Inspect retrieval or run evaluations | [Evaluation](../backend/evaluation/README.md) |
| Deploy or diagnose a release | [Railway runbook](guides/railway-setup.md) |

## Understand and plan

| Document | Scope |
| --- | --- |
| [Client brief](client-brief.md) | Product requirements and desired future corpus; not an implementation claim |
| [Architecture](architecture.md) | Current services, authorization, data and model boundaries |
| [Chat-turn workflow](../backend/CHAT_TURN_WORKFLOW.md) | Send button through retrieval, validation, persistence and SSE |
| [Project status and remaining work](todos.md) | Implemented capabilities, release gates and decisions |
| [QA implementation checklist](qa-suite-todo.md) | Completed and pending QA layers |
| [QA findings](qa-findings-2026-09-05.md) | Live permission and assistant-budget findings, with proposed fixes |
| [Reliable research plan](assistant-research-plan.md) | Limit root causes, measured capacity experiment, protected answers and secure continuation |
| [Permission fix](security-fix-2026-09-06.md) | Server-only persistence, rollout and regression evidence |
| [Repository audit](repository-audit.md) | Findings from the 2026-09-05 working-tree review; fixes await decisions |
| [Railway design and release history](guides/railway-deployment-plan.md) | Deployment rationale and dated evidence |

## Historical and reference material

- [Retrieval tuning results](../backend/evaluation/results/tuning-summary.md) describe
  the old chunk layout. The current labels were remapped and rerun on September 5.
- [Answer benchmark](../backend/evaluation/benchmarks/filings_deep_research_v1.md)
  has an executable companion and a recorded failing baseline; human acceptance remains pending.
- [First SEC-parser metrics](../backend/ingestion/metrics/first_step_metrics_2026-08-26_00-27-41.md)
  are a dated local measurement.
- [Archived ingestion](../backend/ingestion/archive/README.md) is reference-only.
  Its old commands are not supported setup instructions.
- The local [image backup](../azure-image-backups/README.md) and
  [storage backup](../azure-storage-backups/README.md) notes describe the unrelated
  invoice-review app; these files were untracked when the audit began.

## Keep documentation current

Implementation facts come from code, dependency manifests and migrations. Environment
examples are explicit operator profiles and can differ from settings defaults.
Keep those differences in [configuration.md](configuration.md), rather than copying
unlabeled limits into multiple guides.

Date external-service observations. A successful local build or a historical release
record does not establish the current production state. Preserve historical metrics;
write a new result when the corpus, model, prompt or chunker changes.
