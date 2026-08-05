from __future__ import annotations

import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
from urllib import error


def _load_module():
    path = Path("scripts/phase_9f_smoke.py")
    spec = importlib.util.spec_from_file_location("phase_9f_smoke", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class _Response:
    def __init__(self, payload, status: int = 200):
        self.payload = payload
        self.status = status

    def read(self):
        import json

        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _Opener:
    def __init__(self, mapping=None, exc=None):
        self.mapping = mapping or {}
        self.exc = exc or {}
        self.requests = []

    def open(self, req, timeout=0):
        self.requests.append((req.full_url, req.get_method(), dict(req.header_items()), timeout))
        if req.full_url in self.exc:
            raise self.exc[req.full_url]
        return _Response(self.mapping[req.full_url])


def _http_error(url: str, code: int, detail: str):
    body = io.BytesIO((f'{{"detail": "{detail}"}}').encode("utf-8"))
    return error.HTTPError(url, code, detail, hdrs=None, fp=body)


def test_public_health_success() -> None:
    smoke = _load_module()
    opener = _Opener(
        mapping={
            "http://127.0.0.1:8000/health": {"status": "ok"},
            "http://127.0.0.1:8000/openapi.json": {"paths": {"/health": {"get": {}}}},
        }
    )
    out = io.StringIO()
    code = smoke.main(env={}, opener=opener, out=out)
    assert code == 0
    assert "[PASS] health" in out.getvalue()


def test_public_health_failure() -> None:
    smoke = _load_module()
    opener = _Opener(exc={"http://127.0.0.1:8000/health": _http_error("http://127.0.0.1:8000/health", 503, "down")})
    out = io.StringIO()
    code = smoke.main(env={}, opener=opener, out=out)
    assert code == 1
    assert "[FAIL] health" in out.getvalue()


def test_authenticated_checks() -> None:
    smoke = _load_module()
    env = {
        "SCHOOLOS_SMOKE_BEARER_TOKEN": "super-secret-token",
        "SCHOOLOS_SMOKE_TENANT_SLUG": "greenwood",
    }
    opener = _Opener(
        mapping={
            "http://127.0.0.1:8000/health": {"status": "ok"},
            "http://127.0.0.1:8000/openapi.json": {"paths": {"/health": {"get": {}}}},
            "http://127.0.0.1:8000/leadership/onboarding/status": {"run_status": "in_progress"},
            "http://127.0.0.1:8000/leadership/onboarding/readiness": {"blocker_count": 0},
            "http://127.0.0.1:8000/leadership/imports/summary": {"total_batches": 1},
            "http://127.0.0.1:8000/leadership/academic-structure/summary": {"canonical_class_count": 1},
            "http://127.0.0.1:8000/leadership/people/summary": {"active_students": 1},
            "http://127.0.0.1:8000/leadership/families/summary": {"total_active_relationships": 1},
        }
    )
    out = io.StringIO()
    code = smoke.main(env=env, opener=opener, out=out)
    assert code == 0
    methods = {method for _, method, _, _ in opener.requests}
    assert methods == {"GET"}
    assert "super-secret-token" not in out.getvalue()


def test_missing_credentials_skip_behavior() -> None:
    smoke = _load_module()
    opener = _Opener(
        mapping={
            "http://127.0.0.1:8000/health": {"status": "ok"},
            "http://127.0.0.1:8000/openapi.json": {"paths": {}},
        }
    )
    out = io.StringIO()
    code = smoke.main(env={"SCHOOLOS_SMOKE_TENANT_SLUG": "greenwood"}, opener=opener, out=out)
    assert code == 0
    assert "[SKIP] onboarding_status" in out.getvalue()


def test_timeout_handling() -> None:
    smoke = _load_module()
    opener = _Opener(exc={"http://127.0.0.1:8000/health": TimeoutError("too slow")})
    out = io.StringIO()
    code = smoke.main(env={}, opener=opener, out=out)
    assert code == 1
    assert "TimeoutError" in out.getvalue()


def test_http_error_handling() -> None:
    smoke = _load_module()
    env = {
        "SCHOOLOS_SMOKE_BEARER_TOKEN": "token-value",
        "SCHOOLOS_SMOKE_TENANT_SLUG": "greenwood",
    }
    opener = _Opener(
        mapping={
            "http://127.0.0.1:8000/health": {"status": "ok"},
            "http://127.0.0.1:8000/openapi.json": {"paths": {}},
            "http://127.0.0.1:8000/leadership/onboarding/status": {"run_status": "in_progress"},
        },
        exc={
            "http://127.0.0.1:8000/leadership/onboarding/readiness": _http_error(
                "http://127.0.0.1:8000/leadership/onboarding/readiness", 500, "boom"
            ),
            "http://127.0.0.1:8000/leadership/imports/summary": _http_error(
                "http://127.0.0.1:8000/leadership/imports/summary", 500, "boom"
            ),
            "http://127.0.0.1:8000/leadership/academic-structure/summary": _http_error(
                "http://127.0.0.1:8000/leadership/academic-structure/summary", 404, "missing"
            ),
            "http://127.0.0.1:8000/leadership/people/summary": _http_error(
                "http://127.0.0.1:8000/leadership/people/summary", 404, "missing"
            ),
            "http://127.0.0.1:8000/leadership/families/summary": _http_error(
                "http://127.0.0.1:8000/leadership/families/summary", 404, "missing"
            ),
        },
    )
    out = io.StringIO()
    code = smoke.main(env=env, opener=opener, out=out)
    assert code == 1
    assert "[FAIL] onboarding_readiness" in out.getvalue()
    assert "[SKIP] academic_structure_summary" in out.getvalue()


def test_token_and_database_url_never_logged() -> None:
    smoke = _load_module()
    env = {
        "SCHOOLOS_SMOKE_BASE_URL": "http://user:pass@127.0.0.1:8000",
        "SCHOOLOS_SMOKE_BEARER_TOKEN": "top-secret-token",
        "SCHOOLOS_SMOKE_TENANT_SLUG": "greenwood",
        "DATABASE_URL": "postgresql://secret-user:secret-pass@prod/schoolos",
    }
    opener = _Opener(
        mapping={
            "http://user:pass@127.0.0.1:8000/health": {"status": "ok"},
            "http://user:pass@127.0.0.1:8000/openapi.json": {"paths": {}},
            "http://user:pass@127.0.0.1:8000/leadership/onboarding/status": {"run_status": "in_progress"},
            "http://user:pass@127.0.0.1:8000/leadership/onboarding/readiness": {"blocker_count": 0},
            "http://user:pass@127.0.0.1:8000/leadership/imports/summary": {"total_batches": 0},
            "http://user:pass@127.0.0.1:8000/leadership/academic-structure/summary": {"canonical_class_count": 1},
            "http://user:pass@127.0.0.1:8000/leadership/people/summary": {"active_students": 1},
            "http://user:pass@127.0.0.1:8000/leadership/families/summary": {"total_active_relationships": 1},
        }
    )
    out = io.StringIO()
    code = smoke.main(env=env, opener=opener, out=out)
    text = out.getvalue()
    assert code == 0
    assert "top-secret-token" not in text
    assert "secret-pass" not in text
    assert "user:pass" not in text
    assert "postgresql://" not in text


def test_non_zero_failure_exit() -> None:
    smoke = _load_module()
    opener = _Opener(
        mapping={
            "http://127.0.0.1:8000/health": {"status": "ok"},
        },
        exc={
            "http://127.0.0.1:8000/openapi.json": _http_error("http://127.0.0.1:8000/openapi.json", 500, "broken"),
        },
    )
    out = io.StringIO()
    assert smoke.main(env={}, opener=opener, out=out) == 1


def test_no_mutation_http_methods_are_used() -> None:
    smoke = _load_module()
    opener = _Opener(
        mapping={
            "http://127.0.0.1:8000/health": {"status": "ok"},
            "http://127.0.0.1:8000/openapi.json": {"paths": {}},
        }
    )
    smoke.main(env={}, opener=opener, out=io.StringIO())
    assert all(method == "GET" for _, method, _, _ in opener.requests)