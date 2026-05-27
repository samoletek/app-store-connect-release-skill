# ASC Release Skill

Codex skill for preparing localized App Store release metadata in Markdown and pushing it safely to App Store Connect through the App Store Connect API.

The skill is focused on one job: replace repetitive per-locale App Store Connect form editing for release drafts. It handles app name, subtitle, promotional text, description, keywords, What's New, support URL, marketing URL, and privacy URLs across supported ASC locales.

## What It Contains

- `asc-release/SKILL.md` - workflow instructions for Codex.
- `asc-release/scripts/asc_release.py` - CLI for Markdown templates, validation, pull, dry-run, and apply.
- `asc-release/references/` - Apple API notes, copy guidelines, and release checklist.

## Install

Clone or install this repository as a Codex skill:

```bash
git clone https://github.com/samoletek/app-store-connect-release-skill.git
```

Then copy or symlink `asc-release` into your Codex skills directory if your client does not install skills directly from GitHub.

## CLI Quick Start

```bash
python3 -m venv .venv-asc
.venv-asc/bin/pip install -r asc-release/scripts/requirements.txt

.venv-asc/bin/python asc-release/scripts/asc_release.py init --out release/app-store --locales en-US,ru,ja
.venv-asc/bin/python asc-release/scripts/asc_release.py validate --source release/app-store/locales
.venv-asc/bin/python asc-release/scripts/asc_release.py push --source release/app-store/locales
.venv-asc/bin/python asc-release/scripts/asc_release.py push --source release/app-store/locales --apply --confirm 1234567890
```

Required environment:

```bash
ASC_API_KEY_ID=ABC1234DEF
ASC_API_ISSUER_ID=12345678-1234-1234-1234-123456789012
ASC_API_KEY_PATH=tooling/asc/secrets/AuthKey_ABC1234DEF.p8
ASC_APP_APPLE_ID=1234567890
```

## Safety Defaults

- Dry-run is the default.
- Apply requires `--apply --confirm <numeric App Apple ID>`.
- Existing App Store Connect metadata can be pulled before applying changes.
- Keywords are validated as 100 UTF-8 bytes, matching Apple documentation.
- The skill does not handle screenshots, builds, privacy nutrition labels, age ratings, IAP, or final review submission.

## License

MIT
