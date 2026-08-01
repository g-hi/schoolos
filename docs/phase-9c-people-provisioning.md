# Phase 9C People Provisioning

## Scope
Phase 9C delivers leadership people and families operations using existing tenant-scoped models and role checks. It adds no generic Person model and does not redesign ingestion, authentication, or historical migrations.

## Architecture
- User accounts: `User` remains the account identity model.
- Teacher profile: `Teacher` links to `User` via `user_id`.
- Student profile: `Student` remains non-login by default.
- Family links: `StudentParent` is the parent/guardian relationship model.
- Parent profile model: no dedicated `Parent` ORM profile exists in current backend; parent identity is `User(role="parent")`.

## AccountInvitation Security Design
- Storage model: `AccountInvitation`.
- Raw token lifecycle: generated only at issue time, returned once in immediate response.
- Token hashing: SHA-256 hash persisted as `token_hash`.
- States: pending, accepted, revoked, expired.
- Acceptance: `POST /auth/accept-invitation` validates token hash, expiry, revoke/used state, tenant activity, role/email match, then activates account and marks accepted.
- Raw tokens are never recoverable after issue and are never exposed via list endpoints.

## Provisioning Transactions
- Teacher provisioning:
  1. Validate tenant and email uniqueness by role policy.
  2. Create/reuse inactive teacher `User`.
  3. Create `Teacher` profile.
  4. Optionally issue invitation.
  5. Audit and commit atomically.
- Parent provisioning:
  1. Create/reuse inactive parent `User`.
  2. Optionally seed `StudentParent` links.
  3. Optionally issue invitation.
  4. Audit and commit atomically.
- Student provisioning:
  1. Create `Student` without login account.
  2. Optionally seed parent/guardian links.
  3. Optionally create canonical initial enrollment.
  4. Audit and commit.

## Account and Relationship Lifecycle
- Account activation/deactivation: leadership endpoint updates `User.is_active`; deactivation revokes pending invitations.
- Family relationship lifecycle: leadership create/list/patch endpoints update `StudentParent` relation type, primary flag, and active flag.
- Parent-access compatibility: inactive relationship rows deny parent-student access, while legacy rows with `is_active IS NULL` remain treated as active for compatibility.

## Tenant, Role, and Audit Controls
- Tenant scope enforced through tenant resolution and DB context.
- Leadership operations require `principal` or `school_admin` role.
- Parent and public activation routes stay contract-specific.
- Audit events include provisioning, invitation issuance/revocation/acceptance, account status changes, and family lifecycle updates.

## Migration
- Revision: `1a9d5e7c3b21`.
- Chain: single-head migration chain with prior Phase 9B3 revisions retained in ancestry.
- No historical migration rewrite.

## Operational Setup Workflow
1. Provision teacher or parent profile and inactive account.
2. Issue invitation.
3. Deliver one-time activation material through approved channel.
4. User activates account.
5. Leadership confirms profile consistency.
6. Link parent/guardian to students.
7. Verify parent access.
8. Deactivate obsolete relationships/accounts without deleting history.

## Reconciliation Diagnostics
- People summary highlights:
  - teachers without accounts
  - parents without accounts
  - users without matching role profiles
  - inactive users with active profiles
  - pending/expired invitation counts
- Family summary highlights:
  - students without active parent/guardian links
  - students with multiple active links
  - inactive historical relationships
  - cross-tenant inconsistency count
- Current UI presents count-based diagnostics and guided actions; no automatic repair is implemented.

## Compatibility Boundaries
- No row-level reconciliation payload currently returned by summary endpoints.
- Parent profile remains account-backed (`User`) rather than standalone ORM profile.
- Invitation acceptance remains public token-based endpoint and does not auto-login user.

## Phase 9D Dependencies
- Import-history and batch reconciliation orchestration remain out of Phase 9C scope.
- Future operational hardening can add governed delivery channels and richer diagnostics endpoints.