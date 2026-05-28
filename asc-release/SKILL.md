---
name: asc-release
description: "Prepare localized App Store release metadata and safely push it to App Store Connect with the App Store Connect API. Use when Codex needs to draft, translate, review, validate, pull, dry-run, or apply App Store product page texts across many locales: app name, subtitle, promotional text, description, keywords, What's New, support URL, marketing URL, privacy URLs, appInfoLocalizations, appStoreVersionLocalizations, ASC API keys, .p8 JWT auth, App Store Connect draft release preparation, or replacing repetitive App Store Connect web UI save-by-locale work. Do not use for runtime App Store Server API transaction validation or in-app UI string localization."
---

# ASC Release

Use this skill to prepare release-ready App Store metadata as Markdown first, then apply it to an existing App Store Connect app record through the App Store Connect API.

This skill is intentionally narrower than a full App Store Connect API playbook. It focuses on the release draft metadata flow that is painful in the web UI: many locales, the same fields, repeated Save buttons, and high risk of overwriting existing copy.

## Core Workflow

1. Inspect the app context and the current App Store Connect state before writing.
2. Establish one canonical source locale, usually the primary locale already in App Store Connect.
3. Prepare localized release texts in Markdown files under `release/app-store/locales/`.
4. Validate every locale locally before touching ASC.
5. Show the user a compact locale/field summary and a dry-run API diff.
6. Apply only after explicit approval and `--confirm <APP_APPLE_ID>`.
7. Pull back from ASC after apply if you need an audit snapshot.

Use the bundled CLI at `scripts/asc_release.py` for deterministic work:

```bash
python asc-release/scripts/asc_release.py init --out release/app-store --locales en-US,ru,ja
python asc-release/scripts/asc_release.py validate --source release/app-store/locales
python asc-release/scripts/asc_release.py pull --out release/app-store/current --write
python asc-release/scripts/asc_release.py push --source release/app-store/locales
python asc-release/scripts/asc_release.py push --source release/app-store/locales --apply --confirm 1234567890
```

Install script dependencies in the target project:

```bash
python3 -m venv .venv-asc
.venv-asc/bin/pip install -r asc-release/scripts/requirements.txt
```

## Required Setup

The app record must already exist in App Store Connect. The API is for managing existing apps; do not try to create the initial app card through this skill.

Ask the user to create or provide a Team API key with a role that can edit metadata, usually App Manager or Admin. Store secrets outside git:

```bash
ASC_API_KEY_ID=ABC1234DEF
ASC_API_ISSUER_ID=12345678-1234-1234-1234-123456789012
ASC_API_KEY_PATH=tooling/asc/secrets/AuthKey_ABC1234DEF.p8
ASC_APP_APPLE_ID=1234567890
```

The script also accepts `ASC_KEY_ID`, `ASC_ISSUER_ID`, `ASC_KEY_PATH`, and `ASC_APP_ID` aliases.

Never paste `.p8` content into chat. Never commit `.p8`, `.env`, pulled audit snapshots containing private unreleased copy, or generated JWTs.

## Markdown Format

Use one Markdown file per locale. The filename is the ASC locale code:

```markdown
# en-US

## Name
Example Game

## Subtitle
Fast puzzle battles

## Promotional Text
New season, new boards, and sharper daily challenges.

## Description
Plain-text App Store description.

Line breaks are allowed. HTML is not.

## Keywords
puzzle,strategy,battle,logic

## What's New
Version 1.2 improves onboarding and fixes level sync.

## Support URL
https://example.com/support

## Marketing URL
https://example.com

## Privacy Policy URL
https://example.com/privacy

## Privacy Choices URL
https://example.com/privacy-choices
```

The CLI maps fields to Apple resources:

`appInfoLocalizations`: `name`, `subtitle`, `privacyPolicyUrl`, `privacyChoicesUrl`

`appStoreVersionLocalizations`: `promotionalText`, `description`, `keywords`, `whatsNew`, `supportUrl`, `marketingUrl`

## Validation Rules

Run validation before every push. Treat failures as release blockers.

Important limits:

| Field | Limit |
|---|---:|
| `name` | 2-30 characters |
| `subtitle` | 30 characters |
| `promotionalText` | 170 characters |
| `description` | 4000 characters |
| `whatsNew` | 4000 characters |
| `keywords` | 100 characters |
| URLs | 255 characters |

Validate keywords as the App Store Connect UI presents them: 100 characters. Do not use UTF-8 byte length for this field.

Required for a complete release locale: `name`, `description`, `keywords`, and `supportUrl`. `whatsNew` is not available for the first app version, but is required for version updates.

## Safe Push Policy

Default to dry-run. Never use `--apply` until the user approves the displayed diff.

For an app that already has manually entered metadata, run `pull --write` first and compare against the proposed Markdown. Do not silently overwrite human-edited App Store Connect copy.

When adding a new locale, create both `appInfoLocalizations` and `appStoreVersionLocalizations`. Apple warns that mismatched localization sets between app info and app store version can block submission.

When pushing multiple locales, prefer one locale at a time for first setup:

```bash
python asc-release/scripts/asc_release.py push --source release/app-store/locales --locale ja
python asc-release/scripts/asc_release.py push --source release/app-store/locales --locale ja --apply --confirm 1234567890
```

Batch pushes are acceptable for routine updates after the workflow has been proven on the app.

## Copy Guidance

Read `references/copy-guidelines.md` before generating or translating metadata. The short version:

- Produce native-quality localized copy for each target language, not literal translation.
- Rewrite cramped fields such as `subtitle`, `promotionalText`, and `keywords` for the local market instead of preserving source sentence structure.
- Generate keywords as local ASO search terms, not as direct translations.
- Do not duplicate app name or company name in keywords.
- Do not use competitor names.
- Avoid awkward, machine-translated, or meme-like phrasing in every locale.
- Keep App Store copy professional even when the app or game is playful.
- Say clearly when a locale is LLM-localized draft copy and recommend native-speaker review before production for important markets.

## API Notes

Read `references/apple-api-notes.md` when changing API behavior or debugging ASC responses. It summarizes the relevant official Apple docs: auth, locale shortcodes, metadata resources, editable states, error handling, and rate limits.

Read `references/release-checklist.md` before declaring a release draft ready. This skill handles text metadata. It does not upload screenshots, app previews, builds, age ratings, privacy nutrition labels, export compliance, Game Center, IAP, or final review submission unless the target project already has separate tooling for those surfaces.
