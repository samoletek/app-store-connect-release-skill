# Copy Guidelines For Localized App Store Metadata

Use this reference before drafting, translating, or reviewing localized App Store release copy.

## Per-Field Rules

`name`

- Keep the brand/app name unchanged unless the user asks to localize it.
- If the name includes a descriptor, localize only the descriptor when it helps discovery.
- Fit 2-30 characters.

`subtitle`

- Treat as a localized positioning line, not a literal translation.
- Fit 30 characters. German, Russian, Polish, Finnish, and similar languages usually need compression.

`promotionalText`

- Use for current features, event copy, seasonal hooks, or launch messages.
- Fit 170 characters.
- It can be changed without submitting a new app version, so keep it separate from permanent product description copy.

`description`

- Write plain text with meaningful line breaks.
- Preserve feature order agreed with the user.
- No HTML.
- Fit 4000 characters.

`keywords`

- Build local ASO search terms, not direct translations.
- Fit 100 UTF-8 bytes, not 100 characters.
- Comma-separate terms.
- Do not duplicate app name or company name.
- Do not include competitor names.
- Avoid spaces after commas unless a phrase needs an internal space; spaces consume bytes.
- If no real ASO data is available, label the list as best-effort and recommend native/ASO review before production.

`whatsNew`

- Use concise release notes.
- It is unavailable for the first version and required for updates.
- Keep it factual; avoid vague "minor fixes" copy unless that is truly all the release contains.

URLs

- Prefer one shared HTTPS support URL and privacy policy URL unless a locale needs a regional legal page.
- Support pages should contain actual contact information where local law requires it.

## Translation Quality

- Use formal, professional language unless the user explicitly wants a casual market voice.
- Adapt idioms, cultural references, examples, measurements, and date formats.
- For high-value markets, recommend native review before production apply.
- Do not push machine-generated copy to production when the locale has a `$comment` or note marking it as placeholder.

## Review Table

Before applying, show a table like this:

```text
locale  name  subtitle  promo  description  keywords(bytes)  whatsNew
en-US   12/30 24/30     91/170 1340/4000    84/100           180/4000
ja      8/30  14/30     52/170 840/4000     96/100           78/4000
```

If a user cannot read a target script, call that out and recommend native review instead of pretending the generated copy is proven.
