# Azure container image backup

> Recovery material for the separate **invoice-review** application, not a
> Document Copilot runtime dependency. Azure resource/deletion statements below
> are the August 29, 2026 recovery record, not current cloud verification.
> The September 5 audit checked local checksums only; it did not restore resources.

This directory contains an offline Docker image backup for the stopped Azure
Container App named `invoice-review`.

The image was downloaded from Azure Container Registry and validated with
`docker load` before the original registry was deleted on 2026-08-29. The
archive can be used to recreate the registry image if the Container App is
needed again.

## Backup details

| Field | Value |
| --- | --- |
| Archive | `invoice-review-2026-08-29/invoice-review-linux-amd64.tar` |
| Local Docker tag | `invoice-review:azure-backup-2026-08-29` |
| Platform | `linux/amd64` |
| Uncompressed archive size | 84,477,952 bytes (about 81 MiB) |
| Image digest | `sha256:e1053b404b6b17cfbf796cfb89239866601207797072b471c0776a33cf767ada` |
| Archive SHA-256 | `22399db0cee95f04ec58c11899c6b4d4c9d0187b04c6619bacc4ff5dd38c7863` |
| Original registry | `invoicereviewdgaj72no5dcoi.azurecr.io` (deleted) |
| Original repository | `invoice-review` |

The original Azure Container Registry was deleted to end its Basic-tier fixed
daily charge. The stopped Container App still exists, but it cannot start
until this image is pushed to a registry that Azure Container Apps can access.

## What this archive contains

The TAR file contains the deployable Docker image: its Linux filesystem,
application code copied into the image during the build, installed
dependencies, image configuration, and metadata.

It does **not** contain:

- the original Git repository or its history;
- Azure Key Vault secret values injected at runtime;
- the Azure Container App resource or its configuration;
- Azure role assignments or registry configuration;
- data from the mounted Azure Files share `invoice-review-data`.

The original storage account was later backed up and deleted. Its recovery
copy and restore instructions are in
[`../azure-storage-backups/README.md`](../azure-storage-backups/README.md).

Treat the archive as private. A Docker image can contain any files or values
that were included at build time, even if they are not visible in the source
repository now. The TAR is intentionally ignored by Git to prevent accidental
publication and repository bloat.

## Verify integrity

From the repository root, run:

```bash
shasum -a 256 azure-image-backups/invoice-review-2026-08-29/invoice-review-linux-amd64.tar
```

The result must be:

```text
22399db0cee95f04ec58c11899c6b4d4c9d0187b04c6619bacc4ff5dd38c7863
```

Do not use the archive if the checksum differs.

## Load it into Docker locally

Docker Desktop or another Docker engine must be running.

```bash
docker load --input azure-image-backups/invoice-review-2026-08-29/invoice-review-linux-amd64.tar

docker image inspect invoice-review:azure-backup-2026-08-29 \
  --format 'ID={{.Id}} OS={{.Os}} Architecture={{.Architecture}} Size={{.Size}}'
```

The expected image ID is the image digest shown in the table above, and the
platform should be `linux/amd64`.

## Restore it for Azure Container Apps

These commands create a new Basic registry, push the archived image, grant the
existing managed identity permission to pull it, and reconnect the stopped
Container App. Creating the registry resumes its fixed daily charge.

Choose a globally unique lowercase registry name before running the commands:

```bash
AZURE_SUBSCRIPTION_ID="0f44867b-67d5-4e79-8eab-efad913c9299"
AZURE_RESOURCE_GROUP="rg-invoice-review"
NEW_ACR_NAME="replace-with-a-globally-unique-name"
RESTORED_IMAGE="invoice-review:restored-2026-08-29"
MANAGED_IDENTITY_ID="/subscriptions/0f44867b-67d5-4e79-8eab-efad913c9299/resourceGroups/rg-invoice-review/providers/Microsoft.ManagedIdentity/userAssignedIdentities/invoice-review-identity"

az account set --subscription "$AZURE_SUBSCRIPTION_ID"

docker load --input azure-image-backups/invoice-review-2026-08-29/invoice-review-linux-amd64.tar

az acr create \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --name "$NEW_ACR_NAME" \
  --sku Basic \
  --location northeurope

az acr login --name "$NEW_ACR_NAME"

docker tag \
  invoice-review:azure-backup-2026-08-29 \
  "$NEW_ACR_NAME.azurecr.io/$RESTORED_IMAGE"

docker push "$NEW_ACR_NAME.azurecr.io/$RESTORED_IMAGE"
```

Grant the existing managed identity permission to pull from the new registry:

```bash
NEW_ACR_ID="$(az acr show \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --name "$NEW_ACR_NAME" \
  --query id \
  --output tsv)"

IDENTITY_PRINCIPAL_ID="$(az identity show \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --name invoice-review-identity \
  --query principalId \
  --output tsv)"

az role assignment create \
  --assignee-object-id "$IDENTITY_PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal \
  --role AcrPull \
  --scope "$NEW_ACR_ID"
```

Reconnect the Container App and point it at the restored image:

```bash
az containerapp registry set \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --name invoice-review \
  --server "$NEW_ACR_NAME.azurecr.io" \
  --identity "$MANAGED_IDENTITY_ID"

az containerapp update \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --name invoice-review \
  --image "$NEW_ACR_NAME.azurecr.io/$RESTORED_IMAGE" \
  --min-replicas 0
```

Setting `--min-replicas 0` avoids the previous always-on idle charge. Review
the app configuration and costs before starting it:

```bash
az containerapp show \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --name invoice-review \
  --query '{runningStatus:properties.runningStatus,minReplicas:properties.template.scale.minReplicas,image:properties.template.containers[0].image}' \
  --output table

az containerapp start \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --name invoice-review
```

After restoration, test the application before relying on it. The original
storage account was deleted, so restore and reconnect the Azure Files share
using [`../azure-storage-backups/README.md`](../azure-storage-backups/README.md).
The application also still depends on its Key Vault secrets, Document
Intelligence account, and Foundry model deployment.

## Backup care

Keep a second copy of the TAR file on another disk or trusted private backup
location. This local file is now the recovery source for the deleted registry;
if it is lost and the original source repository cannot rebuild the same image,
the archived deployment cannot be recovered exactly.
