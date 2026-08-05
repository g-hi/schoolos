# Phase 9F Release Checklist

## Repository

- [x] Correct branch (`feature/phase-9f-release-readiness`)
- [x] Clean working tree at validation start
- [x] One Alembic head (`c4f7a8e2d911`)
- [x] No accidental secrets observed in changed files and command output
- [x] No untracked temporary files introduced by Batch 2 validation
- [x] No destructive migration executed

## Backend

- [x] Full pytest suite (`425 passed`, `2 skipped`, `0 failed`)
- [x] Route inventory (covered via API and onboarding/openapi checks)
- [x] Tenant isolation (covered by onboarding readiness and lifecycle regression tests)
- [x] Authorization (leadership and onboarding auth checks passing)
- [ ] Migration upgrade (documented local verification gap: local DB unavailable)
- [ ] Migration downgrade (documented local verification gap: local DB unavailable)
- [ ] Migration re-upgrade (documented local verification gap: local DB unavailable)
- [x] Health endpoint contract (`/health` route present)

## Frontend

- [x] Focused tests (onboarding flow file passes)
- [x] Full test suite (`25` files, `190` tests, `0` failures)
- [x] Production build (successful)
- [x] Onboarding route generated (`/onboarding`)
- [x] No TypeScript errors in build
- [x] No sensitive fallback data observed in build output

## Deployment

- [x] Render backend environment variables reviewed (`DATABASE_URL`, `APP_ENV`, `SECRET_KEY`)
- [x] Render frontend API URL handling reviewed (NEXT_PUBLIC based)
- [ ] Database connectivity (local runtime check blocked by unavailable DB)
- [x] Migration execution strategy reviewed (`alembic upgrade head` before app start)
- [x] Backend health endpoint configured (`/health`)
- [ ] Frontend load (requires live deployed environment)
- [ ] Login (requires live deployed environment)
- [ ] Leadership route access (requires live deployed environment)
- [ ] Onboarding status (requires live deployed environment)
- [ ] Readiness (requires live deployed environment)
- [ ] Imports history (requires live deployed environment)
- [ ] No browser console errors (requires live deployed environment)
- [x] Render deploy branch policy understood (`master` deploys after feature merge)
- [x] Backend CORS hardening configured via `CORS_ALLOWED_ORIGINS` (no credentialed wildcard)

## Local Environment Limitations

- [ ] Public smoke checks against local gateway (local service unavailable during validation)
- [ ] Authenticated smoke checks (no local credentials provided by design)

## Rollback

- [ ] Previous backend deploy identified (deployment platform step)
- [ ] Previous frontend deploy identified (deployment platform step)
- [x] Migration rollback safety documented
- [x] No destructive data rollback attempted automatically