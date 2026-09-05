# Azure AI Foundry setup

The backend sends every Responses and embeddings request through the OpenAI-compatible
v1 endpoint on one Azure AI Foundry resource. The Foundry project organizes the Azure
resource but is not the runtime endpoint because project endpoints do not route
embedding requests.

## Recorded resources

| Resource | Name | Location |
|---|---|---|
| Resource group | `rg-10K-club` | West Europe |
| Foundry resource (`AIServices`) | `foundry-10k-club` | East US |
| Foundry project | `10k-club` | East US |
| Log Analytics workspace | `law-10k-club` | East US |
| Application Insights | `appi-10k-club` | East US |

These are the recorded project resources, not a fresh cloud inventory. The
August 28–29, 2026 rollout recorded a system-assigned identity, enabled project
management, and these `GlobalStandard` deployments/capacities:

| Deployment | Model | Version | Capacity | RPM | TPM |
|---|---|---:|---:|---:|---:|
| `assistant-gpt-5-6-terra` | `gpt-5.6-terra` | `2026-07-09` | 100 | 100 | 100,000 |
| `keywords-gpt-5-4-nano` | `gpt-5.4-nano` | `2026-03-17` | 25 | 25 | 25,000 |
| `embeddings-text-embedding-3-small` | `text-embedding-3-small` | `1` | 10 | 10 | 10,000 |

Recheck deployment state and effective quota before a release. All three should
report `Succeeded`; the old allocation record is not a current quota guarantee.

## Verify with Azure CLI

```sh
az account show --query '{name:name,state:state}' --output table
az group show --name rg-10K-club \
  --query '{name:name,location:location,state:properties.provisioningState}' \
  --output table
az cognitiveservices account show \
  --name foundry-10k-club \
  --resource-group rg-10K-club \
  --query '{kind:kind,location:location,state:properties.provisioningState,projectManagement:properties.allowProjectManagement}' \
  --output table
az cognitiveservices account project show \
  --name foundry-10k-club \
  --resource-group rg-10K-club \
  --project-name 10k-club \
  --query '{name:name,location:location,state:properties.provisioningState}' \
  --output table
az cognitiveservices account deployment list \
  --name foundry-10k-club \
  --resource-group rg-10K-club \
  --query '[].{deployment:name,model:properties.model.name,version:properties.model.version,sku:sku.name,capacity:sku.capacity,state:properties.provisioningState}' \
  --output table
```

If the intended profile is still the recorded one, these commands restore its
assistant/keyword capacity. They change Azure allocation; first verify the current
subscription, deployment state, and required capacity:

```sh
az cognitiveservices account deployment update \
  --name foundry-10k-club \
  --resource-group rg-10K-club \
  --deployment-name assistant-gpt-5-6-terra \
  --sku-name GlobalStandard \
  --sku-capacity 100

az cognitiveservices account deployment update \
  --name foundry-10k-club \
  --resource-group rg-10K-club \
  --deployment-name keywords-gpt-5-4-nano \
  --sku-name GlobalStandard \
  --sku-capacity 25
```

If Azure CLI authentication has expired, run `az login`, confirm the intended
subscription, and repeat the read-only verification before changing resources.

## Application configuration

Use `https://foundry-10k-club.openai.azure.com/openai/v1/` as
`AZURE_OPENAI_ENDPOINT`. Retrieve a key only when configuring a secret store:

```sh
az cognitiveservices account keys list \
  --name foundry-10k-club \
  --resource-group rg-10K-club \
  --query key1 \
  --output tsv
```

Never commit, log, or paste the returned key into documentation. The current
resource/project creation procedure follows Microsoft's
[Foundry project guide](https://learn.microsoft.com/en-us/azure/foundry/how-to/create-projects?view=foundry-classic),
and the runtime endpoint follows its
[SDK and endpoint guidance](https://learn.microsoft.com/en-us/azure/foundry/how-to/develop/sdk-overview).

## Assistant turn budget

The table below is the **recorded operator profile**, also present in the Railway
runbook and `.env.example`. Current Python defaults differ for four token limits;
see [the comparison](../configuration.md#assistant-limits-defaults-versus-example-profile).
These are per-turn controls, not a shared quota limiter:

| Limit | Value |
|---|---:|
| Model requests | 10 |
| Total tool calls | 8 |
| Filing searches | 5 |
| Surrounding-chunk reads | 2 |
| Cumulative input tokens | 60,000 |
| Input tokens in one request | 32,000 |
| Output tokens in one request | 3,000 |
| Cumulative output tokens | 6,000 |
| Search passages per call | 10 |
| Passage preview | 400 characters |
| Keyword-extraction output | 800 tokens |
| Streaming execution deadline | 180 seconds |

PydanticAI checks input tokens before every assistant request. During the recorded
rollout Azure returned HTTP 400 from Responses `input_tokens.count` for this model, so
the Azure model adapter serializes the same request locally and uses a calibrated,
conservative ASCII estimate, fixed overhead, and a stricter non-ASCII surcharge.
Completed Responses supply provider-reported usage for the cumulative run counter.
The earlier profile's arithmetic (60,000 input plus ten 3,000-token output caps)
is a planning estimate, not a 90,000-token quota guarantee. Concurrent turns,
retries, request reservations, and separately metered keyword/embedding calls can
still throttle. The newer Python defaults also change that calculation. Diagnose
live throttling from the numeric response headers recorded in Railway logs.

See Microsoft's [quota and capacity documentation](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/quota)
and its [429 retry-versus-escalation guidance](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/quota#when-to-retry-vs-when-to-escalate).

## Model diagnostics and distributed traces

The existing operations notes record a `10k-club-model-diagnostics` setting sending
`RequestResponse` and `AzureOpenAIRequestUsage` to `law-10k-club`, with 30-day
retention and a 0.1 GB/day ingestion cap. They also record the other diagnostic
categories, platform metrics, Application Insights log export, OTel metrics, live
metrics, and performance counters as disabled. Recheck these hosted settings;
the September 5 documentation audit did not query Azure.

The recorded tracing destination is the workspace-based `appi-10k-club` resource
connected to the Foundry project. The uncommitted backend tracing implementation
uses `APPLICATION_INSIGHTS_CONNECTION_STRING` as a secret. An explicit tracing
profile without intentional prompt/output capture is:

```dotenv
AZURE_MONITOR_TRACING_ENABLED=true
AZURE_MONITOR_CAPTURE_CONTENT=false
AZURE_MONITOR_TRACE_SAMPLE_RATE=1
```

Tracing defaults to disabled in code and `.env.example`. The earlier notes used
`AZURE_MONITOR_CAPTURE_CONTENT=true` for temporary diagnosis; that is a separate
content opt-in and is allowed even in the production profile.

The parent span carries `app.trace_id`, matching the assistant log correlation ID.
It covers the assistant run and its retrieval/grounding work, not authentication,
turn preparation, database completion, or SSE delivery. Child spans cover assistant
model, keyword, and retrieval-embedding calls. The direct embedding span currently
omits standard input-token usage because its usage mapper expects `input_tokens`
instead of the embeddings response's `prompt_tokens`.

The direct-call instrumentation does not explicitly record embedding vectors.
However, **content capture off is not a complete content-redaction guarantee**:
OpenTelemetry records exception messages and stack traces by default. Application
log sanitization does not sanitize spans. See
[audit F03](../repository-audit.md#f03-tracing-can-record-exception-content-with-content-capture-disabled)
and [F12](../repository-audit.md#f12-usage-reporting-is-incomplete-across-model-workloads).
Review those findings before enabling production exports.

The backend disables automatic framework/HTTP instrumentation, Azure log and
metric export, and local exporter retry storage. Configuration is process-wide;
restart the backend to change it.

Useful Log Analytics queries:

```kusto
dependencies
| where cloud_RoleName == "10k-club.document-copilot-backend"
| where timestamp > ago(2h)
| project timestamp, operation_Id, name, duration, success, customDimensions
| order by timestamp desc
```

```kusto
AzureDiagnostics
| where ResourceProvider == "MICROSOFT.COGNITIVESERVICES"
| where TimeGenerated > ago(2h)
| extend details = parse_json(properties_s)
| project TimeGenerated, Category,
    model=tostring(details.modelDeploymentName),
    promptTokens=toint(details.promptTokens),
    cachedTokens=toint(details.cachedTokens),
    outputTokens=toint(coalesce(details.generatedTokens, details.completionTokens)),
    timeToFirstTokenMs=toint(details.timeToFirstTokenMs),
    DurationMs, CorrelationId
| order by TimeGenerated desc
```

Azure diagnostic and trace ingestion can incur charges. The daily cap limits normal
Log Analytics ingestion, but it is a safety guard rather than an immediate cutoff;
sampling and content capture should still be reduced after the investigation. New
records can take several minutes to become queryable even after the ingestion
endpoint has accepted them.
