# Share selected sound favorites with a provider

Provider favorites reuse sound identities and chosen descriptors across projects.
They are preferences for discovery, not source admission or listening approval.
Project annotations remain local unless explicitly promoted.

```text
avo cli sfx favorites-show --project <absolute avo.project.json> --json
avo cli sfx favorite-promote --project <absolute avo.project.json> --request <absolute promotion.json> --json
avo cli sfx favorite-remove --project <absolute avo.project.json> --request <absolute removal.json> --json
```

The corresponding MCP tools share the native handlers. Promotion and removal
confirm the exact request bytes. Inspection reads metadata without scanning
libraries, decoding audio, running models or initializing a timeline.

## Promote a chosen identity

A promotion request uses `avo.sfx-provider.schema.json#/$defs/request` with
`operation: "favorite-promote"`, an operation ID, actor/reason, the exact current
project provider and `expectedProviderDocument` from `favorites-show`. Include
the current `expectedGeneration`, selected `entryId`/`entryRevision`, and `fields`
chosen from `description`, `category`, `material`, `tags` and `variantGroup`.
An empty field list shares only the sound identity as a favorite.

Only an available entry in that saved catalogue generation qualifies. Promotion
does not refresh source availability. The identity combines the exact library ID
and source SHA-256; it does not contain the original locator or project name.
Selected descriptors, actor/reason and provenance hashes remain auditable. Private
paths, secret-like values, rights and marker payloads cannot enter these records.

The existing provider manifest holds at most 500 favorites under
`routingOverrides.sfxFavorites`, within a 1 MiB whole-document budget. Existing
provider settings are preserved. Publication checks the current project/provider,
contained target, exact preference bytes and catalogue generation under the
existing writer guards. A changed input requires inspection and a new request.

## Use preferences in a selected scan

Set `useProviderFavorites: true` in a normal explicit `sfx scan` request. It is
off by default. The scan freezes the inspected preference identity and seeds only
new entries whose freshly observed bytes and library ID match a favorite.
Existing entries and project annotations retain their choices.

Seeded entries and search results expose `curationOrigin` with the provider,
preference document hash and favorite identity. Rights stay unknown until locally
documented, and perceptual markers need their own review. No project media,
license, acoustic measurement or historical approval is imported from a favorite.
The ordinary scanner can reuse its independently verified same-byte measurements.

A partial scan binds its exact preference snapshot in the resume token. Changed
preferences, a disabled selection or another context cannot continue that batch;
restart the scan explicitly. Ordinary scans and older entries need no migration.

## Remove shared recommendations

A `favorite-remove` request supplies the current provider, preference document
hash, favorite ID and operation ID/actor/reason. It removes that recommendation
from future selected scans. Existing project curation, canonical sound, rights,
markers and listening decisions remain under their original owners.
