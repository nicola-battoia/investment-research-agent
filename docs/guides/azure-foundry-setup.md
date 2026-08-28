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
It contains these `GlobalStandard` deployments at capacity 10:

| Deployment | Model | Version |
|---|---|---|
| `assistant-gpt-5-6-terra` | `gpt-5.6-terra` | `2026-07-09` |
| `keywords-gpt-5-4-nano` | `gpt-5.4-nano` | `2026-03-17` |
| `embeddings-text-embedding-3-small` | `text-embedding-3-small` | `1` |

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
