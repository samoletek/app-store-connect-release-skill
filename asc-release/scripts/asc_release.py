#!/usr/bin/env python3
"""Prepare, validate, pull, and push localized App Store release metadata.

The source-of-truth format is Markdown: one file per ASC locale, or one
multi-locale Markdown file with "# <locale>" sections.

This script deliberately handles only localized text metadata:
appInfoLocalizations and appStoreVersionLocalizations.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


API_BASE = "https://api.appstoreconnect.apple.com"
USER_AGENT = "asc-release-skill/1.0"
JWT_LIFETIME_SECONDS = 1140
JWT_REFRESH_AFTER_SECONDS = 900

APP_INFO_FIELDS = ("name", "subtitle", "privacyPolicyUrl", "privacyChoicesUrl")
VERSION_FIELDS = (
    "promotionalText",
    "description",
    "keywords",
    "whatsNew",
    "supportUrl",
    "marketingUrl",
)
ALL_FIELDS = APP_INFO_FIELDS + VERSION_FIELDS

COMPLETE_RELEASE_REQUIRED = ("name", "description", "keywords", "supportUrl")
CREATE_APP_INFO_REQUIRED = ("name",)
CREATE_VERSION_REQUIRED = ("description", "keywords")

EDITABLE_APP_INFO_STATES = {
    "PREPARE_FOR_SUBMISSION",
    "WAITING_FOR_REVIEW",
    "READY_FOR_REVIEW",
    "DEVELOPER_REJECTED",
    "REJECTED",
    "METADATA_REJECTED",
}
EDITABLE_VERSION_STATES = {
    "PREPARE_FOR_SUBMISSION",
    "WAITING_FOR_REVIEW",
    "READY_FOR_REVIEW",
    "DEVELOPER_REJECTED",
    "REJECTED",
    "METADATA_REJECTED",
}

LOCALE_RE = re.compile(r"^[a-z]{2,3}(-[A-Z][a-z]{3})?(-[A-Z]{2})?$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
STATE_ERROR_FIELD_RE = re.compile(r"Attribute '(?P<field>[A-Za-z][A-Za-z0-9_]*)'")

LOCALE_CODES = {
    "ar-SA",
    "bn-BD",
    "ca",
    "cs",
    "da",
    "de-DE",
    "el",
    "en-AU",
    "en-CA",
    "en-GB",
    "en-US",
    "es-ES",
    "es-MX",
    "fi",
    "fr-CA",
    "fr-FR",
    "gu-IN",
    "he",
    "hi",
    "hr",
    "hu",
    "id",
    "it",
    "ja",
    "kn-IN",
    "ko",
    "ml-IN",
    "mr-IN",
    "ms",
    "nl-NL",
    "no",
    "or-IN",
    "pa-IN",
    "pl",
    "pt-BR",
    "pt-PT",
    "ro",
    "ru",
    "sk",
    "sl-SI",
    "sv",
    "ta-IN",
    "te-IN",
    "th",
    "tr",
    "uk",
    "ur-PK",
    "vi",
    "zh-Hans",
    "zh-Hant",
}

FIELD_LABELS = {
    "name": "Name",
    "subtitle": "Subtitle",
    "promotionalText": "Promotional Text",
    "description": "Description",
    "keywords": "Keywords",
    "whatsNew": "What's New",
    "supportUrl": "Support URL",
    "marketingUrl": "Marketing URL",
    "privacyPolicyUrl": "Privacy Policy URL",
    "privacyChoicesUrl": "Privacy Choices URL",
}

FIELD_ALIASES = {
    "name": "name",
    "appname": "name",
    "title": "name",
    "subtitle": "subtitle",
    "promotionaltext": "promotionalText",
    "promo": "promotionalText",
    "promotext": "promotionalText",
    "description": "description",
    "keywords": "keywords",
    "keyword": "keywords",
    "whatsnew": "whatsNew",
    "whatnew": "whatsNew",
    "releasenotes": "whatsNew",
    "supporturl": "supportUrl",
    "support": "supportUrl",
    "marketingurl": "marketingUrl",
    "marketing": "marketingUrl",
    "privacypolicyurl": "privacyPolicyUrl",
    "privacyurl": "privacyPolicyUrl",
    "privacy": "privacyPolicyUrl",
    "privacychoicesurl": "privacyChoicesUrl",
    "privacychoiceurl": "privacyChoicesUrl",
}


@dataclass
class Issue:
    level: str
    locale: str
    field: str
    message: str


class ASCError(Exception):
    def __init__(self, status: int, body: Any, headers: dict[str, str] | None = None):
        self.status = status
        self.body = body
        self.headers = headers or {}
        super().__init__(f"ASC HTTP {status}: {error_summary(body)}")


@dataclass
class ASCConfig:
    key_id: str
    issuer_id: str
    key_path: Path
    app_id: str

    @classmethod
    def from_env(cls, app_id_override: str | None = None) -> "ASCConfig":
        try:
            from dotenv import load_dotenv

            load_dotenv(override=False)
        except Exception:
            pass

        key_id = env_first("ASC_API_KEY_ID", "ASC_KEY_ID")
        issuer_id = env_first("ASC_API_ISSUER_ID", "ASC_ISSUER_ID")
        key_path_raw = env_first("ASC_API_KEY_PATH", "ASC_KEY_PATH")
        app_id = app_id_override or env_first(
            "ASC_APP_APPLE_ID",
            "ASC_APP_ID",
            "ASC_APP_APPLE_ID_PRODUCTION",
            required=False,
        )
        missing = []
        if not key_id:
            missing.append("ASC_API_KEY_ID")
        if not issuer_id:
            missing.append("ASC_API_ISSUER_ID")
        if not key_path_raw:
            missing.append("ASC_API_KEY_PATH")
        if not app_id:
            missing.append("ASC_APP_APPLE_ID")
        if missing:
            raise SystemExit("Missing required environment: " + ", ".join(missing))

        key_path = Path(key_path_raw).expanduser()
        if not key_path.is_absolute():
            key_path = Path.cwd() / key_path
        if not key_path.is_file():
            raise SystemExit(f"ASC key file not found: {key_path}")

        return cls(
            key_id=str(key_id),
            issuer_id=str(issuer_id),
            key_path=key_path,
            app_id=str(app_id),
        )


class ASCClient:
    def __init__(self, config: ASCConfig, verbose: bool = False):
        self.config = config
        self.verbose = verbose
        self._token = ""
        self._token_created = 0.0

    def token(self) -> str:
        now = time.time()
        if self._token and now - self._token_created < JWT_REFRESH_AFTER_SECONDS:
            return self._token

        try:
            import jwt
        except ImportError as exc:
            raise SystemExit(
                "PyJWT is required for ASC API calls. Install scripts/requirements.txt."
            ) from exc

        issued_at = int(now)
        private_key = self.config.key_path.read_text(encoding="utf-8")
        self._token = jwt.encode(
            {
                "iss": self.config.issuer_id,
                "iat": issued_at,
                "exp": issued_at + JWT_LIFETIME_SECONDS,
                "aud": "appstoreconnect-v1",
            },
            private_key,
            algorithm="ES256",
            headers={"kid": self.config.key_id, "typ": "JWT"},
        )
        self._token_created = now
        return self._token

    def request(
        self,
        method: str,
        path_or_url: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        retry_post: bool = False,
    ) -> Any:
        url = build_url(path_or_url, params)
        payload = None if body is None else json.dumps(body).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.token()}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"

        max_attempts = 4 if method != "POST" or retry_post else 1
        for attempt in range(max_attempts):
            if self.verbose:
                print(f"{method} {url}", file=sys.stderr)
            req = urllib.request.Request(url, data=payload, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    raw = resp.read()
                    if not raw:
                        return None
                    return json.loads(raw.decode("utf-8"))
            except urllib.error.HTTPError as exc:
                raw = exc.read()
                parsed = parse_json_or_text(raw)
                headers_dict = {k: v for k, v in exc.headers.items()}
                should_retry = exc.code in {429, 500, 502, 503, 504}
                if should_retry and attempt < max_attempts - 1:
                    delay = retry_delay(headers_dict, attempt)
                    print(
                        f"HTTP {exc.code}; retrying in {delay:.1f}s: {error_summary(parsed)}",
                        file=sys.stderr,
                    )
                    time.sleep(delay)
                    continue
                raise ASCError(exc.code, parsed, headers_dict) from exc
            except urllib.error.URLError as exc:
                if attempt < max_attempts - 1:
                    delay = min(30.0, 2.0 * (attempt + 1))
                    print(f"Network error; retrying in {delay:.1f}s: {exc}", file=sys.stderr)
                    time.sleep(delay)
                    continue
                raise

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self.request("GET", path, params=params)

    def get_all(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        next_url: str | None = path
        next_params = dict(params or {})
        while next_url:
            body = self.get(next_url, next_params)
            out.extend(body.get("data", []))
            next_url = (body.get("links") or {}).get("next")
            next_params = {}
        return out

    def post(self, path: str, body: dict[str, Any]) -> Any:
        return self.request("POST", path, body=body, retry_post=False)

    def patch(self, path: str, body: dict[str, Any]) -> Any:
        return self.request("PATCH", path, body=body)


def env_first(*names: str, required: bool = True) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    if required:
        return None
    return None


def build_url(path_or_url: str, params: dict[str, Any] | None = None) -> str:
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        url = path_or_url
    else:
        url = API_BASE + path_or_url
    if params:
        query = urllib.parse.urlencode(params, doseq=True)
        sep = "&" if "?" in url else "?"
        url = url + sep + query
    return url


def parse_json_or_text(raw: bytes) -> Any:
    if not raw:
        return None
    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def retry_delay(headers: dict[str, str], attempt: int) -> float:
    raw = headers.get("Retry-After") or headers.get("retry-after")
    if raw:
        try:
            return max(1.0, min(120.0, float(raw)))
        except ValueError:
            pass
    return min(60.0, 3.0 * (2**attempt))


def error_summary(body: Any) -> str:
    if isinstance(body, dict) and isinstance(body.get("errors"), list):
        parts = []
        for item in body["errors"]:
            code = item.get("code", "")
            detail = item.get("detail") or item.get("title") or ""
            pointer = (item.get("source") or {}).get("pointer") or (
                item.get("source") or {}
            ).get("parameter")
            if pointer:
                parts.append(f"{code} {pointer}: {detail}")
            else:
                parts.append(f"{code}: {detail}")
        return "; ".join(parts)
    return str(body)


def normalize_heading(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def field_from_heading(text: str) -> str | None:
    return FIELD_ALIASES.get(normalize_heading(text))


def strip_outer_blank_lines(lines: list[str]) -> str:
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines).strip()


def parse_markdown_file(path: Path) -> dict[str, dict[str, str]]:
    text = path.read_text(encoding="utf-8")
    results: dict[str, dict[str, str]] = {}
    filename_locale = path.stem if LOCALE_RE.match(path.stem) else None
    current_locale = filename_locale
    current_field: str | None = None
    buffer: list[str] = []

    if current_locale:
        results.setdefault(current_locale, {})

    def flush() -> None:
        nonlocal buffer
        if current_locale and current_field:
            value = strip_outer_blank_lines(buffer[:])
            if current_field == "keywords":
                value = " ".join(value.split())
            results.setdefault(current_locale, {})[current_field] = value
        buffer = []

    for line in text.splitlines():
        heading = HEADING_RE.match(line)
        if heading:
            hashes, title = heading.groups()
            level = len(hashes)
            if level == 1 and LOCALE_RE.match(title.strip()):
                flush()
                current_locale = title.strip()
                results.setdefault(current_locale, {})
                current_field = None
                continue
            if level >= 2:
                flush()
                current_field = field_from_heading(title)
                continue
        if current_locale and current_field:
            buffer.append(line)
    flush()
    return results


def load_markdown_source(source: Path) -> dict[str, dict[str, str]]:
    source = source.expanduser()
    if source.is_dir():
        files = sorted(source.glob("*.md"))
    elif source.is_file():
        files = [source]
    else:
        raise SystemExit(f"Source not found: {source}")
    if not files:
        raise SystemExit(f"No Markdown files found in {source}")

    merged: dict[str, dict[str, str]] = {}
    for file in files:
        parsed = parse_markdown_file(file)
        for locale, fields in parsed.items():
            merged.setdefault(locale, {}).update(fields)
    return merged


def validate_metadata(
    metadata: dict[str, dict[str, str]],
    *,
    allow_partial: bool,
    allow_unknown_locale: bool,
) -> list[Issue]:
    issues: list[Issue] = []
    for locale, fields in sorted(metadata.items()):
        if not LOCALE_RE.match(locale):
            issues.append(Issue("error", locale, "<locale>", "invalid ASC locale code shape"))
        elif locale not in LOCALE_CODES and not allow_unknown_locale:
            issues.append(
                Issue("error", locale, "<locale>", "not in bundled Apple ASC locale catalog")
            )

        if not allow_partial:
            for field in COMPLETE_RELEASE_REQUIRED:
                if not fields.get(field):
                    issues.append(Issue("error", locale, field, "required for release metadata"))

        for field, value in fields.items():
            if field not in ALL_FIELDS:
                continue
            if value is None:
                continue
            if value == "":
                continue
            if field == "name":
                if len(value) < 2:
                    issues.append(Issue("error", locale, field, "must be at least 2 characters"))
                if len(value) > 30:
                    issues.append(Issue("error", locale, field, f"{len(value)}/30 characters"))
                if value != value.strip():
                    issues.append(Issue("warning", locale, field, "leading/trailing whitespace"))
            elif field == "subtitle" and len(value) > 30:
                issues.append(Issue("error", locale, field, f"{len(value)}/30 characters"))
            elif field == "promotionalText" and len(value) > 170:
                issues.append(Issue("error", locale, field, f"{len(value)}/170 characters"))
            elif field == "description" and len(value) > 4000:
                issues.append(Issue("error", locale, field, f"{len(value)}/4000 characters"))
            elif field == "whatsNew" and len(value) > 4000:
                issues.append(Issue("error", locale, field, f"{len(value)}/4000 characters"))
            elif field == "keywords":
                keyword_bytes = len(value.encode("utf-8"))
                if keyword_bytes > 100:
                    issues.append(Issue("error", locale, field, f"{keyword_bytes}/100 UTF-8 bytes"))
                if ", " in value:
                    issues.append(
                        Issue("warning", locale, field, "space after comma wastes keyword bytes")
                    )
                if value.startswith(",") or value.endswith(","):
                    issues.append(Issue("warning", locale, field, "leading/trailing comma"))
                for token in [p.strip() for p in value.split(",") if p.strip()]:
                    if len(token) <= 2:
                        issues.append(
                            Issue("warning", locale, field, f"short keyword token: {token!r}")
                        )
            elif field.endswith("Url"):
                if len(value) > 255:
                    issues.append(Issue("error", locale, field, f"{len(value)}/255 characters"))
                parsed = urllib.parse.urlparse(value)
                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    issues.append(Issue("error", locale, field, "must be a complete http(s) URL"))
                elif parsed.scheme != "https":
                    issues.append(Issue("warning", locale, field, "prefer HTTPS URLs"))
    return issues


def print_issues(issues: list[Issue]) -> None:
    if not issues:
        print("OK: metadata validates")
        return
    for issue in issues:
        marker = "ERROR" if issue.level == "error" else "WARN"
        print(f"{marker}: {issue.locale} {issue.field}: {issue.message}")


def summarize(metadata: dict[str, dict[str, str]]) -> None:
    print("locale  name  subtitle  promo  description  keywords(bytes)  whatsNew")
    for locale, fields in sorted(metadata.items()):
        row = [
            locale,
            ratio(fields.get("name"), 30),
            ratio(fields.get("subtitle"), 30),
            ratio(fields.get("promotionalText"), 170),
            ratio(fields.get("description"), 4000),
            bytes_ratio(fields.get("keywords"), 100),
            ratio(fields.get("whatsNew"), 4000),
        ]
        print("  ".join(row))


def ratio(value: str | None, limit: int) -> str:
    if not value:
        return "-"
    return f"{len(value)}/{limit}"


def bytes_ratio(value: str | None, limit: int) -> str:
    if not value:
        return "-"
    return f"{len(value.encode('utf-8'))}/{limit}"


def md_for_locale(locale: str, fields: dict[str, str]) -> str:
    chunks = [f"# {locale}", ""]
    for field in (
        "name",
        "subtitle",
        "promotionalText",
        "description",
        "keywords",
        "whatsNew",
        "supportUrl",
        "marketingUrl",
        "privacyPolicyUrl",
        "privacyChoicesUrl",
    ):
        chunks.append(f"## {FIELD_LABELS[field]}")
        chunks.append(fields.get(field, "").strip())
        chunks.append("")
    return "\n".join(chunks).rstrip() + "\n"


def command_init(args: argparse.Namespace) -> int:
    out = Path(args.out).expanduser()
    locales_dir = out / "locales"
    locales_dir.mkdir(parents=True, exist_ok=True)
    locales = parse_locale_list(args.locales)
    for locale in locales:
        path = locales_dir / f"{locale}.md"
        if path.exists() and not args.overwrite:
            print(f"skip existing: {path}")
            continue
        fields = {
            "name": args.app_name or "Example App",
            "subtitle": "Replace this subtitle",
            "promotionalText": "Replace this promotional text.",
            "description": "Replace this App Store description.",
            "keywords": "keyword,example,replace",
            "whatsNew": "Replace these release notes, or leave blank for the first version.",
            "supportUrl": args.support_url or "https://example.com/support",
            "marketingUrl": args.marketing_url or "https://example.com",
            "privacyPolicyUrl": args.privacy_url or "https://example.com/privacy",
            "privacyChoicesUrl": "",
        }
        path.write_text(md_for_locale(locale, fields), encoding="utf-8")
        print(f"wrote {path}")
    readme = out / "README.md"
    if not readme.exists() or args.overwrite:
        readme.write_text(
            "App Store release metadata source.\n\n"
            "Validate before push:\n\n"
            "```bash\n"
            "python asc-release/scripts/asc_release.py validate --source release/app-store/locales\n"
            "```\n",
            encoding="utf-8",
        )
    return 0


def parse_locale_list(raw: str) -> list[str]:
    locales = [p.strip() for p in raw.split(",") if p.strip()]
    if not locales:
        raise SystemExit("At least one locale is required")
    bad = [loc for loc in locales if not LOCALE_RE.match(loc)]
    if bad:
        raise SystemExit("Invalid locale code(s): " + ", ".join(bad))
    return locales


def command_validate(args: argparse.Namespace) -> int:
    metadata = load_markdown_source(Path(args.source))
    issues = validate_metadata(
        metadata,
        allow_partial=args.allow_partial,
        allow_unknown_locale=args.allow_unknown_locale,
    )
    summarize(metadata)
    print_issues(issues)
    if any(i.level == "error" for i in issues):
        return 1
    if args.strict and any(i.level == "warning" for i in issues):
        return 1
    return 0


def find_editable_app_info(client: ASCClient, app_id: str) -> dict[str, Any]:
    infos = client.get_all(f"/v1/apps/{app_id}/appInfos", {"limit": 50})
    if not infos:
        raise SystemExit(f"No appInfos found for app {app_id}")
    preferred = [
        item
        for item in infos
        if item.get("attributes", {}).get("state") in EDITABLE_APP_INFO_STATES
    ]
    return preferred[0] if preferred else infos[0]


def find_editable_version(client: ASCClient, app_id: str) -> dict[str, Any] | None:
    versions = client.get_all(
        f"/v1/apps/{app_id}/appStoreVersions",
        {
            "limit": 200,
            "filter[appStoreState]": ",".join(sorted(EDITABLE_VERSION_STATES)),
        },
    )
    if not versions:
        return None
    versions.sort(
        key=lambda item: item.get("attributes", {}).get("createdDate") or "",
        reverse=True,
    )
    return versions[0]


def fetch_current_localizations(
    client: ASCClient, app_id: str
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    app_info = find_editable_app_info(client, app_id)
    version = find_editable_version(client, app_id)

    info_locs = client.get_all(
        f"/v1/appInfos/{app_info['id']}/appInfoLocalizations", {"limit": 200}
    )
    version_locs: list[dict[str, Any]] = []
    if version is not None:
        version_locs = client.get_all(
            f"/v1/appStoreVersions/{version['id']}/appStoreVersionLocalizations",
            {"limit": 200},
        )

    info_by_locale = {
        item.get("attributes", {}).get("locale"): item
        for item in info_locs
        if item.get("attributes", {}).get("locale")
    }
    version_by_locale = {
        item.get("attributes", {}).get("locale"): item
        for item in version_locs
        if item.get("attributes", {}).get("locale")
    }
    return app_info, version, info_by_locale, version_by_locale


def attrs_without_none(item: dict[str, Any] | None) -> dict[str, str]:
    if not item:
        return {}
    attrs = item.get("attributes", {}) or {}
    out = {}
    for field in ALL_FIELDS:
        value = attrs.get(field)
        if isinstance(value, str) and value:
            out[field] = value
    return out


def command_pull(args: argparse.Namespace) -> int:
    config = ASCConfig.from_env(args.app_id)
    client = ASCClient(config, verbose=args.verbose)
    app_info, version, info_by_locale, version_by_locale = fetch_current_localizations(
        client, config.app_id
    )
    print_resource_selection(app_info, version)

    locales = sorted(set(info_by_locale) | set(version_by_locale))
    if args.locale:
        locales = [args.locale]

    if args.write:
        out = Path(args.out).expanduser()
        out.mkdir(parents=True, exist_ok=True)

    for locale in locales:
        fields = {}
        fields.update(attrs_without_none(info_by_locale.get(locale)))
        fields.update(attrs_without_none(version_by_locale.get(locale)))
        text = md_for_locale(locale, fields)
        if args.write:
            path = Path(args.out).expanduser() / f"{locale}.md"
            if path.exists() and not args.overwrite:
                print(f"exists, not overwriting: {path}")
                continue
            path.write_text(text, encoding="utf-8")
            print(f"wrote {path}")
        else:
            print(text)
    return 0


def print_resource_selection(app_info: dict[str, Any], version: dict[str, Any] | None) -> None:
    app_info_state = app_info.get("attributes", {}).get("state", "<unknown>")
    print(f"appInfo: {app_info['id']} state={app_info_state}")
    if version is None:
        print("appStoreVersion: not found")
    else:
        attrs = version.get("attributes", {})
        print(
            "appStoreVersion: "
            f"{version['id']} version={attrs.get('versionString')} "
            f"state={attrs.get('appStoreState')}"
        )


def command_push(args: argparse.Namespace) -> int:
    metadata = load_markdown_source(Path(args.source))
    if args.locale:
        if args.locale not in metadata:
            raise SystemExit(f"Locale {args.locale!r} not found in source")
        metadata = {args.locale: metadata[args.locale]}

    if not args.skip_validation:
        issues = validate_metadata(
            metadata,
            allow_partial=args.allow_partial,
            allow_unknown_locale=args.allow_unknown_locale,
        )
        print_issues(issues)
        if any(i.level == "error" for i in issues):
            return 1
        if args.strict and any(i.level == "warning" for i in issues):
            return 1

    summarize(metadata)
    config = ASCConfig.from_env(args.app_id)
    if args.apply and args.confirm != config.app_id:
        print(
            "Refusing apply: pass --confirm with the exact numeric App Apple ID "
            f"({config.app_id})",
            file=sys.stderr,
        )
        return 2

    client = ASCClient(config, verbose=args.verbose)
    app_info, version, info_by_locale, version_by_locale = fetch_current_localizations(
        client, config.app_id
    )
    print_resource_selection(app_info, version)

    result = PushResult()
    for locale, fields in sorted(metadata.items()):
        try:
            process_locale(
                client,
                locale,
                fields,
                app_info,
                version,
                info_by_locale,
                version_by_locale,
                apply=args.apply,
                no_create=args.no_create,
                result=result,
            )
        except ASCError as exc:
            print(f"ERROR: {locale}: HTTP {exc.status}: {error_summary(exc.body)}")
            result.failed += 1
            if not args.continue_on_error:
                break
    print(
        f"summary: changed_fields={result.changed_fields} "
        f"created={result.created} patched={result.patched} "
        f"skipped_state={result.skipped_state} failed={result.failed}"
    )
    if not args.apply and result.changed_fields:
        print("dry-run only; re-run with --apply --confirm <APP_APPLE_ID> to write")
    return 1 if result.failed else 0


@dataclass
class PushResult:
    changed_fields: int = 0
    created: int = 0
    patched: int = 0
    skipped_state: int = 0
    failed: int = 0


def process_locale(
    client: ASCClient,
    locale: str,
    desired: dict[str, str],
    app_info: dict[str, Any],
    version: dict[str, Any] | None,
    info_by_locale: dict[str, dict[str, Any]],
    version_by_locale: dict[str, dict[str, Any]],
    *,
    apply: bool,
    no_create: bool,
    result: PushResult,
) -> None:
    print(f"\n[{locale}]")
    info_fields = clean_fields(desired, APP_INFO_FIELDS)
    version_fields = clean_fields(desired, VERSION_FIELDS)

    info_current = info_by_locale.get(locale)
    if info_fields:
        if info_current:
            diffs = diff_fields(info_fields, attrs_without_none(info_current))
            render_diff("appInfoLocalization", diffs)
            result.changed_fields += len(diffs)
            if apply and diffs:
                patch_app_info(client, info_current["id"], new_values(diffs))
                result.patched += 1
        elif no_create:
            print("missing appInfoLocalization; --no-create set")
        else:
            missing = [field for field in CREATE_APP_INFO_REQUIRED if not info_fields.get(field)]
            if missing:
                raise SystemExit(f"{locale}: cannot create appInfoLocalization, missing {missing}")
            render_create("appInfoLocalization", info_fields)
            result.changed_fields += len(info_fields)
            if apply:
                created = create_app_info_loc(client, app_info["id"], locale, info_fields)
                info_by_locale[locale] = created
                result.created += 1

    if version is None:
        if version_fields:
            print("missing editable appStoreVersion; version fields cannot be pushed")
            result.failed += 1
        return

    version_current = version_by_locale.get(locale)
    if version_fields:
        if version_current:
            diffs = diff_fields(version_fields, attrs_without_none(version_current))
            render_diff("appStoreVersionLocalization", diffs)
            result.changed_fields += len(diffs)
            if apply and diffs:
                applied, skipped = patch_version_loc_with_state_retry(
                    client, version_current["id"], new_values(diffs)
                )
                result.patched += 1 if applied else 0
                result.skipped_state += len(skipped)
        elif no_create:
            print("missing appStoreVersionLocalization; --no-create set")
        else:
            missing = [field for field in CREATE_VERSION_REQUIRED if not version_fields.get(field)]
            if missing:
                raise SystemExit(
                    f"{locale}: cannot create appStoreVersionLocalization, missing {missing}"
                )
            create_payload = {k: v for k, v in version_fields.items() if k != "whatsNew"}
            render_create("appStoreVersionLocalization", create_payload)
            result.changed_fields += len(create_payload)
            if "whatsNew" in version_fields:
                print("  skip whatsNew on create; Apple blocks it on first versions")
                result.skipped_state += 1
            if apply:
                created = create_version_loc(client, version["id"], locale, create_payload)
                version_by_locale[locale] = created
                result.created += 1


def clean_fields(fields: dict[str, str], allowed: tuple[str, ...]) -> dict[str, str]:
    return {field: fields[field] for field in allowed if fields.get(field)}


def diff_fields(desired: dict[str, str], current: dict[str, str]) -> dict[str, tuple[str, str]]:
    out = {}
    for field, value in desired.items():
        old = current.get(field, "")
        if old != value:
            out[field] = (old, value)
    return out


def new_values(diffs: dict[str, tuple[str, str]]) -> dict[str, str]:
    return {field: new for field, (_, new) in diffs.items()}


def render_diff(kind: str, diffs: dict[str, tuple[str, str]]) -> None:
    if not diffs:
        print(f"  {kind}: no changes")
        return
    print(f"  {kind}:")
    for field, (old, new) in diffs.items():
        print(f"    ~ {field}")
        print(f"      - {compact(old)}")
        print(f"      + {compact(new)}")


def render_create(kind: str, fields: dict[str, str]) -> None:
    print(f"  {kind}: create")
    for field, value in fields.items():
        print(f"    + {field}: {compact(value)}")


def compact(value: str, limit: int = 120) -> str:
    value = value.replace("\n", "\\n")
    if not value:
        return "(empty)"
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def patch_app_info(client: ASCClient, loc_id: str, fields: dict[str, str]) -> None:
    client.patch(
        f"/v1/appInfoLocalizations/{loc_id}",
        {"data": {"type": "appInfoLocalizations", "id": loc_id, "attributes": fields}},
    )


def patch_version_loc(client: ASCClient, loc_id: str, fields: dict[str, str]) -> None:
    client.patch(
        f"/v1/appStoreVersionLocalizations/{loc_id}",
        {
            "data": {
                "type": "appStoreVersionLocalizations",
                "id": loc_id,
                "attributes": fields,
            }
        },
    )


def create_app_info_loc(
    client: ASCClient, app_info_id: str, locale: str, fields: dict[str, str]
) -> dict[str, Any]:
    payload = {
        "data": {
            "type": "appInfoLocalizations",
            "attributes": {"locale": locale, **fields},
            "relationships": {
                "appInfo": {"data": {"type": "appInfos", "id": app_info_id}}
            },
        }
    }
    try:
        return client.post("/v1/appInfoLocalizations", payload)["data"]
    except ASCError as exc:
        if not is_duplicate_error(exc):
            raise
        existing = find_app_info_loc(client, app_info_id, locale)
        if not existing:
            raise
        patch_app_info(client, existing["id"], fields)
        return existing


def create_version_loc(
    client: ASCClient, version_id: str, locale: str, fields: dict[str, str]
) -> dict[str, Any]:
    payload = {
        "data": {
            "type": "appStoreVersionLocalizations",
            "attributes": {"locale": locale, **fields},
            "relationships": {
                "appStoreVersion": {"data": {"type": "appStoreVersions", "id": version_id}}
            },
        }
    }
    try:
        return client.post("/v1/appStoreVersionLocalizations", payload)["data"]
    except ASCError as exc:
        if not is_duplicate_error(exc):
            raise
        existing = find_version_loc(client, version_id, locale)
        if not existing:
            raise
        patch_version_loc_with_state_retry(client, existing["id"], fields)
        return existing


def is_duplicate_error(exc: ASCError) -> bool:
    if exc.status != 409:
        return False
    if not isinstance(exc.body, dict):
        return False
    return any("DUPLICATE" in (err.get("code") or "") for err in exc.body.get("errors", []))


def find_app_info_loc(client: ASCClient, app_info_id: str, locale: str) -> dict[str, Any] | None:
    locs = client.get_all(
        f"/v1/appInfos/{app_info_id}/appInfoLocalizations", {"limit": 200}
    )
    return find_locale_item(locs, locale)


def find_version_loc(client: ASCClient, version_id: str, locale: str) -> dict[str, Any] | None:
    locs = client.get_all(
        f"/v1/appStoreVersions/{version_id}/appStoreVersionLocalizations", {"limit": 200}
    )
    return find_locale_item(locs, locale)


def find_locale_item(items: list[dict[str, Any]], locale: str) -> dict[str, Any] | None:
    for item in items:
        if item.get("attributes", {}).get("locale") == locale:
            return item
    return None


def patch_version_loc_with_state_retry(
    client: ASCClient, loc_id: str, fields: dict[str, str]
) -> tuple[set[str], set[str]]:
    remaining = dict(fields)
    skipped: set[str] = set()
    applied: set[str] = set()
    while remaining:
        try:
            patch_version_loc(client, loc_id, remaining)
            applied.update(remaining)
            return applied, skipped
        except ASCError as exc:
            bad_fields = state_error_fields(exc)
            removable = (bad_fields - skipped) & set(remaining)
            if exc.status != 409 or not removable:
                raise
            for field in sorted(removable):
                print(f"  skip {field}: Apple says field is not editable in this state")
                skipped.add(field)
                remaining.pop(field, None)
    return applied, skipped


def state_error_fields(exc: ASCError) -> set[str]:
    if not isinstance(exc.body, dict):
        return set()
    out = set()
    for err in exc.body.get("errors", []):
        if "STATE_ERROR" not in (err.get("code") or ""):
            continue
        match = STATE_ERROR_FIELD_RE.search(err.get("detail") or "")
        if match:
            out.add(match.group("field"))
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Create Markdown locale templates")
    p_init.add_argument("--out", default="release/app-store")
    p_init.add_argument("--locales", required=True, help="Comma-separated ASC locales")
    p_init.add_argument("--app-name")
    p_init.add_argument("--support-url")
    p_init.add_argument("--marketing-url")
    p_init.add_argument("--privacy-url")
    p_init.add_argument("--overwrite", action="store_true")
    p_init.set_defaults(func=command_init)

    p_validate = sub.add_parser("validate", help="Validate Markdown metadata")
    p_validate.add_argument("--source", default="release/app-store/locales")
    p_validate.add_argument("--allow-partial", action="store_true")
    p_validate.add_argument("--allow-unknown-locale", action="store_true")
    p_validate.add_argument("--strict", action="store_true", help="Warnings fail validation")
    p_validate.set_defaults(func=command_validate)

    p_pull = sub.add_parser("pull", help="Pull current ASC metadata into Markdown")
    p_pull.add_argument("--out", default="release/app-store/current")
    p_pull.add_argument("--write", action="store_true", help="Write files instead of printing")
    p_pull.add_argument("--overwrite", action="store_true")
    p_pull.add_argument("--locale")
    p_pull.add_argument("--app-id")
    p_pull.add_argument("--verbose", action="store_true")
    p_pull.set_defaults(func=command_pull)

    p_push = sub.add_parser("push", help="Dry-run or apply Markdown metadata to ASC")
    p_push.add_argument("--source", default="release/app-store/locales")
    p_push.add_argument("--locale")
    p_push.add_argument("--app-id")
    p_push.add_argument("--apply", action="store_true")
    p_push.add_argument("--confirm", help="Required for --apply: exact numeric App Apple ID")
    p_push.add_argument("--no-create", action="store_true")
    p_push.add_argument("--continue-on-error", action="store_true")
    p_push.add_argument("--skip-validation", action="store_true")
    p_push.add_argument("--allow-partial", action="store_true")
    p_push.add_argument("--allow-unknown-locale", action="store_true")
    p_push.add_argument("--strict", action="store_true", help="Warnings fail validation")
    p_push.add_argument("--verbose", action="store_true")
    p_push.set_defaults(func=command_push)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
