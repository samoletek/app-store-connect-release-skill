# Apple API Notes For Release Metadata

Use this reference when implementing, debugging, or reviewing App Store Connect release metadata automation.

## Official Sources

- App Store Connect API overview: https://developer.apple.com/documentation/AppStoreConnectAPI
- JWT auth: https://developer.apple.com/documentation/appstoreconnectapi/generating-tokens-for-api-requests
- API keys: https://developer.apple.com/documentation/appstoreconnectapi/creating_api_keys_for_app_store_connect_api
- Rate limits: https://developer.apple.com/documentation/appstoreconnectapi/identifying-rate-limits
- Error handling: https://developer.apple.com/documentation/appstoreconnectapi/interpreting-and-handling-errors
- Locale shortcodes: https://developer.apple.com/documentation/appstoreconnectapi/managing-metadata-in-your-app-by-using-locale-shortcodes
- App Info Localizations: https://developer.apple.com/documentation/appstoreconnectapi/app-info-localizations
- App Store Version Localizations: https://developer.apple.com/documentation/appstoreconnectapi/app-store-version-localizations
- Localize app information: https://developer.apple.com/help/app-store-connect/manage-app-information/localize-app-information/
- Platform version metadata: https://developer.apple.com/help/app-store-connect/reference/app-information/platform-version-information
- Required/localizable/editable properties: https://developer.apple.com/help/app-store-connect/reference/app-information/required-localizable-and-editable-properties

## Auth

Use App Store Connect API Team keys for release automation. Team keys use:

- JWT header: `alg=ES256`, `kid=<key id>`, `typ=JWT`.
- JWT payload: `iss=<issuer id>`, `iat=<unix seconds>`, `exp=<unix seconds>`, `aud=appstoreconnect-v1`.
- Most tokens must not live longer than 20 minutes. Reuse a token for a batch, but refresh before expiry.
- Send `Authorization: Bearer <token>`.

Individual keys differ: they use `sub=user` instead of `iss` and have endpoint limitations. Prefer Team keys for app release automation.

## Metadata Resource Split

Apple splits localized App Store metadata across two resource families:

`appInfoLocalizations`:

- `locale`
- `name`
- `subtitle`
- `privacyPolicyUrl`
- `privacyChoicesUrl`
- `privacyPolicyText` for tvOS contexts

`appStoreVersionLocalizations`:

- `locale`
- `promotionalText`
- `description`
- `keywords`
- `whatsNew`
- `supportUrl`
- `marketingUrl`
- relationships to screenshot and preview sets

For a release draft, keep both localization sets aligned. Apple's help states that when app info and app store version do not have the same localization set, submission can fail.

## Field Limits And Required Fields

For iOS release metadata:

- Name: 2-30 characters.
- Subtitle: 30 characters.
- Promotional text: 170 characters.
- Description: 4000 characters, plain text, no HTML.
- Keywords: 100 bytes. Do not validate this as characters.
- What's New: 4000 characters, unavailable for the first version and required for updates.
- Support URL: required and localizable.
- Marketing URL: optional and localizable.

Support URLs must be complete URLs with a protocol. Prefer HTTPS for all release URLs even where Apple examples show HTTP.

## Locale Codes

Use Apple's ASC locale shortcodes, not arbitrary BCP-47 guesses and not Xcode localization folder names. Examples:

- `en-US`, `en-GB`, `de-DE`, `fr-FR`, `pt-BR`
- `ja`, `ko`, `hi`, `ru`, `uk`
- `zh-Hans`, `zh-Hant`
- South Asian locale codes often include a region: `bn-BD`, `gu-IN`, `kn-IN`, `ml-IN`, `mr-IN`, `or-IN`, `pa-IN`, `ta-IN`, `te-IN`, `ur-PK`
- Slovenian is `sl-SI`

When Apple adds locales, update the script locale catalog before pushing.

## Existing App Cards

If the app card already has metadata, always pull current ASC state before applying generated copy. The correct workflow is:

1. Pull `appInfoLocalizations` and `appStoreVersionLocalizations`.
2. Compare pulled copy to proposed Markdown.
3. Dry-run push.
4. Apply only the reviewed diff.

Do not select "first localization" or "first version" casually. Prefer the editable app info and editable app store version associated with the target app Apple ID.

## Errors And Retries

Apple returns JSON:API error objects. Use both HTTP status and `errors[].code`.

- 401: bad JWT, expired token, wrong `aud`, wrong key, or token lifetime too long.
- 403: key role lacks permission.
- 404: wrong resource ID or app not visible to the key.
- 409: state conflicts, duplicates, or fields not editable in the current app state.
- 422: invalid request body, missing required attributes or relationships.
- 429: rate limit exceeded.

Use `source.pointer` and `source.parameter` when present. Retry only 429 and transient 5xx with backoff. For mutating POSTs, avoid blind retries that can create duplicates; verify state first.

## Rate Limits

ASC responses include an `X-Rate-Limit` header with hourly limit and remaining request count for the API key. If the API returns 429 with `RATE_LIMIT_EXCEEDED`, stop or queue the job for later. Metadata pushes should be sequential by locale; parallelizing writes is not worth the risk.
