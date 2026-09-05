# Azure Storage backup

> Recovery material for the separate **invoice-review** application, not a
> Document Copilot runtime dependency. Azure resource/deletion statements below
> are the August 29, 2026 recovery record, not current cloud verification.
> The September 5 audit checked local checksums only; it did not restore resources.

This directory contains the local recovery copy of the deleted Azure Storage
account `invoicereviewdgaj72no5dc` from resource group `rg-invoice-review`.

The account was inventoried, downloaded, and validated before deletion on
2026-08-29. The original account no longer exists in Azure.

## What was in the account

The management-plane inventory found:

- one Azure Files share named `invoice-review-data`;
- one share snapshot from `2026-08-07T00:00:50Z`;
- zero Blob containers;
- zero Queues;
- zero Tables.

AzCopy completed both downloads with zero failed or skipped file transfers.

| Recovery set | Contents | Size |
| --- | --- | ---: |
| `current` | Latest `invoice-review.sqlite3` | 135,168 bytes |
| `snapshot/2026-08-07` | Historical SQLite database plus three PDFs and two JPEGs | 8,531,125 bytes |

Both SQLite databases passed `PRAGMA integrity_check`. The five historical
uploads were also identified successfully as PDF or JPEG files.

## Locations

Latest state:

```text
invoicereviewdgaj72no5dc-2026-08-29/
└── file-shares/invoice-review-data/current/invoice-review-data/
    └── invoice-review.sqlite3
```

Historical snapshot:

```text
invoicereviewdgaj72no5dc-2026-08-29/
└── file-shares/invoice-review-data/snapshots/2026-08-07T00-00-50Z/invoice-review-data/
    ├── invoice-review.sqlite3
    └── uploads/
```

The actual storage data is intentionally ignored by Git because it contains
private application and user data. `README.md` and `SHA256SUMS` remain
trackable.

## Verify the backup

From the repository root, run:

```bash
cd azure-storage-backups/invoicereviewdgaj72no5dc-2026-08-29
shasum -a 256 --check SHA256SUMS
```

Every line must report `OK`.

You can recheck the SQLite databases separately:

```bash
sqlite3 file-shares/invoice-review-data/current/invoice-review-data/invoice-review.sqlite3 \
  'PRAGMA integrity_check;'

sqlite3 file-shares/invoice-review-data/snapshots/2026-08-07T00-00-50Z/invoice-review-data/invoice-review.sqlite3 \
  'PRAGMA integrity_check;'
```

Both commands should return `ok`.

## Choose a recovery set

Use the `current` directory to restore the state that existed immediately
before deletion. It contains the latest database but no upload files.

Use the complete `2026-08-07` snapshot to restore that historical point in
time, including its uploads. Do not mix the snapshot database with the current
directory's files unless you have checked the database references and know the
resulting state is consistent.

## Restore to Azure Files

The following outline recreates a Standard LRS account and a 5 GiB file share.
The storage-account name must be globally unique and might differ from the
deleted name.

```bash
AZURE_SUBSCRIPTION_ID="0f44867b-67d5-4e79-8eab-efad913c9299"
AZURE_RESOURCE_GROUP="rg-invoice-review"
NEW_STORAGE_ACCOUNT="replace-with-a-globally-unique-name"
FILE_SHARE_NAME="invoice-review-data"

az account set --subscription "$AZURE_SUBSCRIPTION_ID"

az storage account create \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --name "$NEW_STORAGE_ACCOUNT" \
  --location northeurope \
  --sku Standard_LRS \
  --kind StorageV2 \
  --https-only true \
  --min-tls-version TLS1_2 \
  --allow-blob-public-access false

az storage share-rm create \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --storage-account "$NEW_STORAGE_ACCOUNT" \
  --name "$FILE_SHARE_NAME" \
  --quota 5 \
  --access-tier TransactionOptimized \
  --enabled-protocols SMB
```

Upload **one** selected recovery directory with Azure Storage Explorer or
AzCopy. For the latest state, the local source directory is:

```text
azure-storage-backups/invoicereviewdgaj72no5dc-2026-08-29/file-shares/invoice-review-data/current/invoice-review-data
```

For the historical state, use:

```text
azure-storage-backups/invoicereviewdgaj72no5dc-2026-08-29/file-shares/invoice-review-data/snapshots/2026-08-07T00-00-50Z/invoice-review-data
```

After uploading, reconnect the Container Apps environment storage mapping:

```bash
NEW_STORAGE_KEY="$(az storage account keys list \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --account-name "$NEW_STORAGE_ACCOUNT" \
  --query '[0].value' \
  --output tsv)"

az containerapp env storage set \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --name invoice-review-env \
  --storage-name invoice-review-storage \
  --azure-file-account-name "$NEW_STORAGE_ACCOUNT" \
  --azure-file-account-key "$NEW_STORAGE_KEY" \
  --azure-file-share-name "$FILE_SHARE_NAME" \
  --access-mode ReadWrite

unset NEW_STORAGE_KEY
```

The Container App also needs its container image restored from
[`../azure-image-backups/README.md`](../azure-image-backups/README.md) before it
can run. Verify both the image and storage configuration before starting the
app.

## Backup care

Keep a second private copy on another disk or trusted backup service. The
deleted Azure file-share snapshot cannot be recovered from Azure; these local
files are now the recovery source. Do not publish them or commit them to Git.
