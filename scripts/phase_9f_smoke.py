from __future__ import annotations

import json
import os
import socket
import sys
from typing import Any, Callable
from urllib import error, parse, request


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SECONDS = 5.0

BASE_URL_ENV = "SCHOOLOS_SMOKE_BASE_URL"
TOKEN_ENV = "SCHOOLOS_SMOKE_BEARER_TOKEN"
TENANT_ENV = "SCHOOLOS_SMOKE_TENANT_SLUG"
TIMEOUT_ENV = "SCHOOLOS_SMOKE_TIMEOUT_SEC"


class SmokeFailure(Exception):
    pass


class CheckResult:
    def __init__(self, name: str, status: str, detail: str):
        self.name = name
        self.status = status
        self.detail = detail


def _safe_base_url(raw_url: str) -> str:
    parsed = parse.urlsplit(raw_url)
    hostname = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    netloc = f"{hostname}{port}"
    return parse.urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def _read_timeout(env: dict[str, str]) -> float:
    raw = env.get(TIMEOUT_ENV, str(DEFAULT_TIMEOUT_SECONDS)).strip()
    try:
        timeout = float(raw)
    except ValueError as exc:
        raise SmokeFailure(f"Invalid {TIMEOUT_ENV} value.") from exc
    if timeout <= 0:
        raise SmokeFailure(f"{TIMEOUT_ENV} must be greater than zero.")
    return timeout


def _normalize_base_url(env: dict[str, str]) -> str:
    base_url = env.get(BASE_URL_ENV, DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
    parsed = parse.urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SmokeFailure(f"Invalid {BASE_URL_ENV} value.")
    return base_url.rstrip("/")


def _json_detail(payload: Any) -> str:
    if isinstance(payload, dict):
        if "detail" in payload:
            return str(payload["detail"])
        return json.dumps(payload, sort_keys=True)
    if isinstance(payload, list):
        return f"list[{len(payload)}]"
    return str(payload)


def _decode_body(raw: bytes) -> Any:
    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _request_json(
    *,
    opener: Any,
    base_url: str,
    path: str,
    headers: dict[str, str],
    timeout: float,
) -> Any:
    req = request.Request(f"{base_url}{path}", headers=headers, method="GET")
    try:
        with opener.open(req, timeout=timeout) as response:
            return _decode_body(response.read())
    except error.HTTPError as exc:
        payload = _decode_body(exc.read())
        raise SmokeFailure(f"HTTP {exc.code} for {path}: {_json_detail(payload)}") from exc
    except (error.URLError, TimeoutError, socket.timeout) as exc:
        raise SmokeFailure(f"Request failed for {path}: {type(exc).__name__}") from exc


def _emit(out, result: CheckResult) -> None:
    print(f"[{result.status}] {result.name}: {result.detail}", file=out)


def _auth_headers(env: dict[str, str]) -> dict[str, str] | None:
    token = env.get(TOKEN_ENV, "").strip()
    tenant = env.get(TENANT_ENV, "").strip()
    if not token or not tenant:
        return None
    return {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Slug": tenant,
    }


def main(
    *,
    env: dict[str, str] | None = None,
    opener: Any | None = None,
    out=None,
) -> int:
    env = dict(os.environ if env is None else env)
    out = sys.stdout if out is None else out
    opener = opener or request.build_opener()

    try:
        base_url = _normalize_base_url(env)
        timeout = _read_timeout(env)
    except SmokeFailure as exc:
        _emit(out, CheckResult(name="configuration", status="FAIL", detail=str(exc)))
        return 1

    _emit(out, CheckResult(name="target", status="INFO", detail=f"Base URL {_safe_base_url(base_url)} | timeout {timeout:.1f}s"))
    failures = 0

    try:
        health = _request_json(opener=opener, base_url=base_url, path="/health", headers={}, timeout=timeout)
        _emit(out, CheckResult(name="health", status="PASS", detail=_json_detail(health)))
    except SmokeFailure as exc:
        _emit(out, CheckResult(name="health", status="FAIL", detail=str(exc)))
        return 1

    try:
        openapi = _request_json(opener=opener, base_url=base_url, path="/openapi.json", headers={}, timeout=timeout)
        paths = openapi.get("paths", {}) if isinstance(openapi, dict) else {}
        _emit(out, CheckResult(name="openapi", status="PASS", detail=f"paths={len(paths)}"))
    except SmokeFailure as exc:
        if "HTTP 404" in str(exc):
            _emit(out, CheckResult(name="openapi", status="SKIP", detail="OpenAPI inventory not available."))
        else:
            _emit(out, CheckResult(name="openapi", status="FAIL", detail=str(exc)))
            failures += 1

    headers = _auth_headers(env)
    checks = [
        ("onboarding_status", "/leadership/onboarding/status", False),
        ("onboarding_readiness", "/leadership/onboarding/readiness", False),
        ("import_summary", "/leadership/imports/summary", False),
        ("academic_structure_summary", "/leadership/academic-structure/summary", True),
        ("people_summary", "/leadership/people/summary", True),
        ("family_summary", "/leadership/families/summary", True),
    ]

    if headers is None:
        for name, _, _ in checks:
            _emit(out, CheckResult(name=name, status="SKIP", detail="Authentication variables not provided."))
        return 0 if failures == 0 else 1

    for name, path, optional in checks:
        try:
            payload = _request_json(opener=opener, base_url=base_url, path=path, headers=headers, timeout=timeout)
            _emit(out, CheckResult(name=name, status="PASS", detail=_json_detail(payload)))
        except SmokeFailure as exc:
            if optional and "HTTP 404" in str(exc):
                _emit(out, CheckResult(name=name, status="SKIP", detail="Endpoint not available in this deployment."))
                continue
            _emit(out, CheckResult(name=name, status="FAIL", detail=str(exc)))
            failures += 1

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())