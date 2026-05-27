# Release Draft Checklist

This checklist prevents overclaiming. The skill handles localized text metadata only. A release draft can still be blocked by other App Store Connect surfaces.

## Text Metadata Covered By This Skill

- App name
- Subtitle
- Promotional text
- Description
- Keywords
- What's New
- Support URL
- Marketing URL
- Privacy policy URL
- Privacy choices URL
- Creation/update of matching app info and app store version localizations

## Before Pull Or Push

- The app record exists in App Store Connect.
- A new editable app version exists if version metadata needs editing.
- The numeric App Apple ID is known.
- The API key can see and edit the app.
- `.p8`, `.env`, and generated JWTs are not committed.
- Current ASC metadata has been pulled if the app card already contains manual edits.

## Before Apply

- `validate` passes.
- The user has reviewed generated copy in Markdown.
- The user has reviewed the dry-run diff.
- New locales have both required fields: `name`, `description`, `keywords`, and `supportUrl`.
- `keywords` are under 100 UTF-8 bytes.
- `whatsNew` is omitted or expected to be skipped for the first version.
- Production apply uses typed confirmation with the numeric App Apple ID.

## Not Covered

Do not claim the app is ready for submission unless these have also been handled manually or by separate project tooling:

- Screenshots and app preview videos for each required display target.
- App icon.
- Build upload and build selection.
- App Review contact details, demo account, and notes.
- Age rating.
- Privacy nutrition labels.
- Export compliance/encryption questions.
- App availability, price, and territories.
- In-app purchases and subscriptions, including review screenshots.
- Game Center configuration.
- Custom product pages and product page optimization.
- Final App Review submission.

## After Apply

- Pull a fresh snapshot from ASC.
- Ask the user to inspect the App Store Connect UI.
- Keep the Markdown source in the app repo if it should remain the source of truth.
- Store audit output outside public repos when unreleased marketing copy is sensitive.
