# Azure AI Foundry setup

The backend sends every Responses and embeddings request through the OpenAI-compatible
v1 endpoint on one Azure AI Foundry resource. The Foundry project organizes the Azure
resource but is not the runtime endpoint because project endpoints do not route
embedding requests.

## Provisioned resources

| Resource | Name | Location |
|---|---|---|
| Resource group | `rg-10K-club` | West Europe |
| Foundry resource (`AIServices`) | `foundry-10k-club` | East US |
| Foundry project | `10k-club` | East US |

The Foundry resource has a system-assigned identity and project management enabled.
It contains these `GlobalStandard` deployments. The capacities and effective rate
limits were verified after the 2026-08-28 reliability rollout:

| Deployment | Model | Version | Capacity | RPM | TPM |
|---|---|---:|---:|---:|---:|
| `assistant-gpt-5-6-terra` | `gpt-5.6-terra` | `2026-07-09` | 100 | 100 | 100,000 |
| `keywords-gpt-5-4-nano` | `gpt-5.4-nano` | `2026-03-17` | 25 | 25 | 25,000 |
| `embeddings-text-embedding-3-small` | `text-embedding-3-small` | `1` | 10 | 10 | 10,000 |

All three deployments must report `Succeeded`. The subscription quota currently
allows these allocations without a quota-increase request.

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

To restore the intended capacity after an accidental change:

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

The backend keeps a normal research turn inside the assistant deployment's quota:

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
| Complete-turn deadline | 180 seconds |

PydanticAI checks input tokens before every assistant request. Azure currently
returns HTTP 400 from the Responses `input_tokens.count` endpoint for this model, so
the Azure model adapter serializes the same request locally and uses a calibrated,
conservative ASCII estimate, fixed overhead, and a stricter non-ASCII surcharge.
Completed Responses
still supply Azure's actual usage, which replaces estimates in the cumulative run
counter. At the maximum ten requests, Azure can reserve up to another 30,000 tokens
from the configured 3,000 output-token cap, leaving an estimated 90,000-token
envelope below the deployment's 100,000 TPM allocation. Azure estimates rate-limit
usage from prompt size and the configured maximum output, so billed-token metrics
alone can look low while a request is still throttled. Diagnose live throttling from
the numeric response headers recorded in Railway logs.

See Microsoft's [quota and capacity documentation](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/quota)
and its [429 retry-versus-escalation guidance](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/quota#when-to-retry-vs-when-to-escalate).
