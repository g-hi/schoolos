"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import RoleGuard from "@/components/auth/role-guard";
import { listClasses } from "@/lib/academic-structure-api";
import {
  FamiliesApiError,
  RelationshipType,
  createFamilyRelationship,
  getFamilySummary,
  listFamilyRelationships,
  updateFamilyRelationship,
  type FamilyRelationship,
  type FamilySummary,
} from "@/lib/families-api";
import {
  InvitationStatus,
  PeopleApiError,
  PersonDirectoryItem,
  PeopleSummary,
  issueInvitation,
  listInvitations,
  listPeople,
  provisionParent,
  provisionStudent,
  provisionTeacher,
  revokeInvitation,
  updateUserStatus,
  getPeopleSummary,
  type InvitationListItem,
} from "@/lib/people-api";

const TABS = [
  "Overview",
  "People",
  "Add Teacher",
  "Add Parent",
  "Add Student",
  "Invitations",
  "Families",
  "Reconciliation",
] as const;

type Tab = (typeof TABS)[number];

type Health = "healthy" | "attention required" | "action required";

type OneTimeMaterial = {
  context: string;
  token: string;
};

function statusTone(level: Health): string {
  if (level === "healthy") return "bg-green-100 text-green-700";
  if (level === "attention required") return "bg-amber-100 text-amber-800";
  return "bg-red-100 text-red-700";
}

function inferHealth(value: number, warnAt = 1): Health {
  if (value <= 0) return "healthy";
  if (value < warnAt) return "attention required";
  return "action required";
}

function parseError(error: unknown): string {
  if (error instanceof PeopleApiError || error instanceof FamiliesApiError) {
    return error.message;
  }
  if (error instanceof Error) return error.message;
  return "Request failed.";
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

function copyText(value: string): void {
  if (typeof navigator === "undefined" || !navigator.clipboard) return;
  void navigator.clipboard.writeText(value);
}

function OneTimePanel({ value, onClose }: { value: OneTimeMaterial | null; onClose: () => void }) {
  if (!value) return null;
  return (
    <section className="rounded-xl border border-amber-300 bg-amber-50 p-4" role="status" aria-live="polite">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold text-amber-900">One-time activation material</h3>
          <p className="mt-1 text-sm text-amber-800">
            Save and deliver this token through an approved channel. It is shown once and is not persisted.
          </p>
        </div>
        <button type="button" className="text-sm text-amber-800 underline" onClick={onClose}>
          Dismiss
        </button>
      </div>
      <div className="mt-3 rounded-lg border border-amber-200 bg-white p-3 text-sm font-mono break-all">{value.token}</div>
      <div className="mt-2 flex items-center gap-2">
        <span className="text-xs text-amber-800">Context: {value.context}</span>
        <button
          type="button"
          className="rounded-md border border-amber-300 px-2 py-1 text-xs text-amber-900"
          onClick={() => copyText(value.token)}
        >
          Copy
        </button>
      </div>
    </section>
  );
}

function OverviewSection({ people, families }: { people: PeopleSummary | null; families: FamilySummary | null }) {
  const cards = [
    { label: "Total active users", value: people?.total_active_users ?? 0, health: "healthy" as Health },
    { label: "Active teachers", value: people?.active_teachers ?? 0, health: "healthy" as Health },
    { label: "Active parents", value: people?.active_parents ?? 0, health: "healthy" as Health },
    { label: "Active students", value: people?.active_students ?? 0, health: "healthy" as Health },
    {
      label: "Teachers without accounts",
      value: people?.teachers_without_user_accounts ?? 0,
      health: inferHealth(people?.teachers_without_user_accounts ?? 0),
    },
    {
      label: "Parents without accounts",
      value: people?.parents_without_user_accounts ?? 0,
      health: inferHealth(people?.parents_without_user_accounts ?? 0),
    },
    {
      label: "Users without matching profiles",
      value: people?.users_without_matching_role_profiles ?? 0,
      health: inferHealth(people?.users_without_matching_role_profiles ?? 0),
    },
    {
      label: "Inactive users with active profiles",
      value: people?.inactive_users_with_active_profiles ?? 0,
      health: inferHealth(people?.inactive_users_with_active_profiles ?? 0),
    },
    { label: "Pending invitations", value: people?.pending_invitations ?? 0, health: inferHealth(people?.pending_invitations ?? 0) },
    { label: "Expired invitations", value: people?.expired_invitations ?? 0, health: inferHealth(people?.expired_invitations ?? 0) },
    { label: "Accepted invitations", value: people?.accepted_invitations ?? 0, health: "healthy" as Health },
    { label: "Revoked invitations", value: people?.revoked_invitations ?? 0, health: "healthy" as Health },
    {
      label: "Active relationships",
      value: families?.total_active_relationships ?? 0,
      health: "healthy" as Health,
    },
    {
      label: "Students without active parent/guardian relationships",
      value: families?.students_with_no_active_parent_guardian_relationship ?? 0,
      health: inferHealth(families?.students_with_no_active_parent_guardian_relationship ?? 0),
    },
    {
      label: "Students with multiple relationships",
      value: families?.students_with_multiple_active_relationships ?? 0,
      health: inferHealth(families?.students_with_multiple_active_relationships ?? 0),
    },
    {
      label: "Primary relationships",
      value: families?.primary_relationships ?? 0,
      health: "healthy" as Health,
    },
    {
      label: "Inactive historical relationships",
      value: families?.inactive_historical_relationships ?? 0,
      health: "attention required" as Health,
    },
  ];

  return (
    <section className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
      {cards.map((item) => (
        <article key={item.label} className="rounded-xl border border-gray-200 bg-white p-4">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-sm font-medium text-gray-700">{item.label}</h3>
            <span className={`rounded-full px-2 py-0.5 text-xs ${statusTone(item.health)}`}>{item.health}</span>
          </div>
          <p className="mt-2 text-2xl font-semibold text-gray-900">{item.value}</p>
        </article>
      ))}
    </section>
  );
}

export default function PeoplePage() {
  const [tab, setTab] = useState<Tab>("Overview");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [peopleSummary, setPeopleSummary] = useState<PeopleSummary | null>(null);
  const [familySummary, setFamilySummary] = useState<FamilySummary | null>(null);

  const [peopleRows, setPeopleRows] = useState<PersonDirectoryItem[]>([]);
  const [peopleTotal, setPeopleTotal] = useState(0);
  const [peopleOffset, setPeopleOffset] = useState(0);
  const [peopleSearch, setPeopleSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [profileFilter, setProfileFilter] = useState("");
  const [hasAccountFilter, setHasAccountFilter] = useState("all");

  const [inviteRows, setInviteRows] = useState<InvitationListItem[]>([]);
  const [inviteTotal, setInviteTotal] = useState(0);
  const [inviteStatus, setInviteStatus] = useState<"all" | InvitationStatus>("all");
  const [inviteRole, setInviteRole] = useState<"all" | "teacher" | "parent">("all");

  const [familyRows, setFamilyRows] = useState<FamilyRelationship[]>([]);
  const [familyActiveOnly, setFamilyActiveOnly] = useState(true);
  const [familyTypeFilter, setFamilyTypeFilter] = useState<"all" | RelationshipType>("all");

  const [studentOptions, setStudentOptions] = useState<PersonDirectoryItem[]>([]);
  const [parentOptions, setParentOptions] = useState<PersonDirectoryItem[]>([]);
  const [classOptions, setClassOptions] = useState<Array<{ id: string; label: string }>>([]);

  const [teacherForm, setTeacherForm] = useState({
    display_name: "",
    email: "",
    employee_id: "",
    max_weekly_hours: "20",
    send_invitation: true,
  });

  const [parentForm, setParentForm] = useState({
    display_name: "",
    email: "",
    phone: "",
    send_invitation: true,
    student_id: "",
    relationship_type: "guardian" as RelationshipType,
    is_primary: false,
  });

  const [studentForm, setStudentForm] = useState({
    name: "",
    class_id: "",
    student_code: "",
    parent_id: "",
    relationship_type: "guardian" as RelationshipType,
    is_primary: false,
    with_enrollment: false,
    enrolled_on: "",
  });

  const [familyCreate, setFamilyCreate] = useState({
    parent_id: "",
    student_id: "",
    relationship_type: "guardian" as RelationshipType,
    is_primary: false,
  });

  const [oneTimeMaterial, setOneTimeMaterial] = useState<OneTimeMaterial | null>(null);

  useEffect(() => {
    return () => {
      setOneTimeMaterial(null);
    };
  }, []);

  useEffect(() => {
    setOneTimeMaterial(null);
  }, [tab]);

  async function loadSummaries() {
    const [p, f] = await Promise.all([getPeopleSummary(), getFamilySummary()]);
    setPeopleSummary(p);
    setFamilySummary(f);
  }

  async function loadPeople() {
    const response = await listPeople({
      search: peopleSearch || undefined,
      role: (roleFilter || undefined) as never,
      status: (statusFilter || undefined) as never,
      profile_status: profileFilter || undefined,
      has_account: hasAccountFilter === "all" ? undefined : hasAccountFilter === "yes",
      limit: 20,
      offset: peopleOffset,
    });
    setPeopleRows(response.items);
    setPeopleTotal(response.total);
  }

  async function loadInvitations() {
    const response = await listInvitations({
      status: inviteStatus === "all" ? undefined : inviteStatus,
      role: inviteRole === "all" ? undefined : inviteRole,
      limit: 20,
      offset: 0,
    });
    setInviteRows(response.items);
    setInviteTotal(response.total);
  }

  async function loadFamilies() {
    const response = await listFamilyRelationships({ active_only: familyActiveOnly });
    setFamilyRows(response);
  }

  async function loadReferenceOptions() {
    const [students, parents, classes] = await Promise.all([
      listPeople({ role: "student", limit: 200, offset: 0 }),
      listPeople({ role: "parent", limit: 200, offset: 0 }),
      listClasses(),
    ]);
    setStudentOptions(students.items);
    setParentOptions(parents.items.filter((row) => Boolean(row.user_id)));
    setClassOptions(classes.map((klass) => ({ id: klass.id, label: `${klass.code ?? "Class"} ${klass.section ?? ""}`.trim() })));
  }

  const loadAll = async () => {
    setLoading(true);
    setError(null);
    try {
      await Promise.all([loadSummaries(), loadPeople(), loadInvitations(), loadFamilies(), loadReferenceOptions()]);
    } catch (err) {
      setError(parseError(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadAll();
  }, []);

  useEffect(() => {
    void loadPeople().catch((err) => setError(parseError(err)));
  }, [peopleOffset, peopleSearch, roleFilter, statusFilter, profileFilter, hasAccountFilter]);

  useEffect(() => {
    void loadInvitations().catch((err) => setError(parseError(err)));
  }, [inviteStatus, inviteRole]);

  useEffect(() => {
    void loadFamilies().catch((err) => setError(parseError(err)));
  }, [familyActiveOnly]);

  const filteredFamilyRows = useMemo(() => {
    if (familyTypeFilter === "all") return familyRows;
    return familyRows.filter((row) => row.relationship_type === familyTypeFilter);
  }, [familyRows, familyTypeFilter]);

  async function handleStatusToggle(row: PersonDirectoryItem, active: boolean) {
    if (!row.user_id) return;
    const confirmed = window.confirm(active ? "Activate this account?" : "Deactivate this account?");
    if (!confirmed) return;
    const reason = !active ? window.prompt("Optional reason for deactivation", "") : "";

    try {
      await updateUserStatus(row.user_id, { is_active: active, reason: reason || null });
      await Promise.all([loadPeople(), loadSummaries()]);
    } catch (err) {
      setError(parseError(err));
    }
  }

  async function handleIssueInvitation(row: PersonDirectoryItem) {
    if (!row.user_id) return;
    try {
      const result = await issueInvitation(row.user_id);
      setOneTimeMaterial({ context: `${row.display_name} invitation`, token: result.activation_token });
      await Promise.all([loadInvitations(), loadSummaries(), loadPeople()]);
    } catch (err) {
      setError(parseError(err));
    }
  }

  async function handleRevokeInvitation(row: InvitationListItem) {
    const confirmed = window.confirm("Revoke this pending invitation?");
    if (!confirmed) return;
    try {
      await revokeInvitation(row.id);
      await Promise.all([loadInvitations(), loadSummaries(), loadPeople()]);
    } catch (err) {
      setError(parseError(err));
    }
  }

  async function submitTeacher(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      const response = await provisionTeacher({
        display_name: teacherForm.display_name,
        email: teacherForm.email,
        employee_id: teacherForm.employee_id || null,
        max_weekly_hours: Number(teacherForm.max_weekly_hours || "20"),
        send_invitation: teacherForm.send_invitation,
      });
      if (response.activation_token) {
        setOneTimeMaterial({ context: `Teacher ${response.email}`, token: response.activation_token });
      }
      setTeacherForm({ display_name: "", email: "", employee_id: "", max_weekly_hours: "20", send_invitation: true });
      await Promise.all([loadPeople(), loadInvitations(), loadSummaries(), loadReferenceOptions()]);
    } catch (err) {
      setError(parseError(err));
    }
  }

  async function submitParent(event: FormEvent) {
    event.preventDefault();
    setError(null);

    const relationships = parentForm.student_id
      ? [{ student_id: parentForm.student_id, relationship_type: parentForm.relationship_type, is_primary: parentForm.is_primary }]
      : [];

    try {
      const response = await provisionParent({
        display_name: parentForm.display_name,
        email: parentForm.email,
        phone: parentForm.phone || null,
        send_invitation: parentForm.send_invitation,
        relationships,
      });
      if (response.activation_token) {
        setOneTimeMaterial({ context: `Parent ${response.email}`, token: response.activation_token });
      }
      setParentForm({
        display_name: "",
        email: "",
        phone: "",
        send_invitation: true,
        student_id: "",
        relationship_type: "guardian",
        is_primary: false,
      });
      await Promise.all([loadPeople(), loadInvitations(), loadSummaries(), loadFamilies(), loadReferenceOptions()]);
    } catch (err) {
      setError(parseError(err));
    }
  }

  async function submitStudent(event: FormEvent) {
    event.preventDefault();
    setError(null);

    const body = {
      name: studentForm.name,
      class_id: studentForm.class_id,
      student_code: studentForm.student_code || null,
      relationships: studentForm.parent_id
        ? [
            {
              parent_id: studentForm.parent_id,
              relationship_type: studentForm.relationship_type,
              is_primary: studentForm.is_primary,
            },
          ]
        : [],
      initial_enrollment:
        studentForm.with_enrollment && studentForm.enrolled_on
          ? {
              class_id: studentForm.class_id,
              enrolled_on: studentForm.enrolled_on,
            }
          : null,
    };

    try {
      await provisionStudent(body);
      setStudentForm({
        name: "",
        class_id: "",
        student_code: "",
        parent_id: "",
        relationship_type: "guardian",
        is_primary: false,
        with_enrollment: false,
        enrolled_on: "",
      });
      await Promise.all([loadPeople(), loadSummaries(), loadFamilies(), loadReferenceOptions()]);
    } catch (err) {
      setError(parseError(err));
    }
  }

  async function submitFamilyRelationship(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await createFamilyRelationship({
        parent_id: familyCreate.parent_id,
        student_id: familyCreate.student_id,
        relationship_type: familyCreate.relationship_type,
        is_primary: familyCreate.is_primary,
      });
      setFamilyCreate({ parent_id: "", student_id: "", relationship_type: "guardian", is_primary: false });
      await Promise.all([loadFamilies(), loadSummaries()]);
    } catch (err) {
      setError(parseError(err));
    }
  }

  async function patchFamilyRelationship(row: FamilyRelationship, body: { is_active?: boolean; is_primary?: boolean; relationship_type?: RelationshipType }) {
    try {
      await updateFamilyRelationship(row.relationship_id, body);
      await Promise.all([loadFamilies(), loadSummaries()]);
    } catch (err) {
      setError(parseError(err));
    }
  }

  return (
    <RoleGuard
      allowedRoles={["principal", "school_admin"]}
      forbiddenMessage="Only school leadership can access the People & Families workspace."
    >
      <main className="space-y-4 p-4 sm:p-6">
        <header className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">People & Families</h1>
            <p className="text-sm text-gray-600">Provisioning, invitations, family relationships and reconciliation diagnostics.</p>
          </div>
          <button type="button" onClick={() => void loadAll()} className="rounded-lg border border-gray-300 px-3 py-2 text-sm">
            Refresh
          </button>
        </header>

        <nav className="flex flex-wrap gap-2" aria-label="People workspace sections">
          {TABS.map((entry) => (
            <button
              key={entry}
              type="button"
              onClick={() => setTab(entry)}
              className={`rounded-full px-3 py-1.5 text-sm ${tab === entry ? "bg-indigo-600 text-white" : "bg-gray-100 text-gray-700"}`}
            >
              {entry}
            </button>
          ))}
        </nav>

        {error ? (
          <section className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
            {error}
            <button className="ml-3 underline" type="button" onClick={() => setError(null)}>
              Dismiss
            </button>
          </section>
        ) : null}

        <OneTimePanel value={oneTimeMaterial} onClose={() => setOneTimeMaterial(null)} />

        {loading ? <p className="text-sm text-gray-600">Loading People & Families workspace...</p> : null}

        {!loading && tab === "Overview" ? <OverviewSection people={peopleSummary} families={familySummary} /> : null}

        {!loading && tab === "People" ? (
          <section className="rounded-xl border border-gray-200 bg-white p-4">
            <h2 className="text-lg font-semibold">People directory</h2>
            <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
              <input
                aria-label="People search"
                className="rounded-md border border-gray-300 px-2 py-1 text-sm"
                placeholder="Search"
                value={peopleSearch}
                onChange={(event) => {
                  setPeopleOffset(0);
                  setPeopleSearch(event.target.value);
                }}
              />
              <select aria-label="Role filter" className="rounded-md border border-gray-300 px-2 py-1 text-sm" value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)}>
                <option value="">All roles</option>
                <option value="teacher">Teacher</option>
                <option value="parent">Parent</option>
                <option value="student">Student</option>
              </select>
              <select aria-label="Account status filter" className="rounded-md border border-gray-300 px-2 py-1 text-sm" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                <option value="">All statuses</option>
                <option value="active">Active</option>
                <option value="inactive">Inactive</option>
              </select>
              <select aria-label="Profile status filter" className="rounded-md border border-gray-300 px-2 py-1 text-sm" value={profileFilter} onChange={(e) => setProfileFilter(e.target.value)}>
                <option value="">All profile states</option>
                <option value="ok">ok</option>
                <option value="missing_teacher_profile">missing_teacher_profile</option>
              </select>
              <select aria-label="Has account filter" className="rounded-md border border-gray-300 px-2 py-1 text-sm" value={hasAccountFilter} onChange={(e) => setHasAccountFilter(e.target.value)}>
                <option value="all">All accounts</option>
                <option value="yes">Has account</option>
                <option value="no">No account</option>
              </select>
            </div>

            <div className="mt-4 overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="text-left text-gray-600">
                    <th className="py-2">Name</th>
                    <th>Role/Profile</th>
                    <th>Email</th>
                    <th>Account</th>
                    <th>Profile consistency</th>
                    <th>Invitation</th>
                    <th>Created</th>
                    <th className="text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {peopleRows.map((row) => (
                    <tr key={`${row.person_id}:${row.user_id ?? "none"}`} className="border-t border-gray-100">
                      <td className="py-2 font-medium text-gray-800">{row.display_name}</td>
                      <td>{row.role} / {row.profile_type}</td>
                      <td>{row.email ?? "-"}</td>
                      <td>{row.has_account ? (row.is_active ? "active" : "inactive") : "no account"}</td>
                      <td>{row.profile_consistency_status}</td>
                      <td>{row.invitation_status ?? "-"}</td>
                      <td>{formatDate(row.created_at)}</td>
                      <td className="text-right">
                        <div className="inline-flex gap-2">
                          {row.user_id ? (
                            <>
                              {row.is_active ? (
                                <button type="button" className="rounded border px-2 py-1" onClick={() => void handleStatusToggle(row, false)}>
                                  Deactivate
                                </button>
                              ) : (
                                <button type="button" className="rounded border px-2 py-1" onClick={() => void handleStatusToggle(row, true)}>
                                  Activate
                                </button>
                              )}
                              <button type="button" className="rounded border px-2 py-1" onClick={() => void handleIssueInvitation(row)}>
                                Issue invitation
                              </button>
                            </>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="mt-3 flex items-center justify-between text-sm">
              <span>Showing {peopleRows.length} of {peopleTotal}</span>
              <div className="flex items-center gap-2">
                <button type="button" className="rounded border px-2 py-1" disabled={peopleOffset <= 0} onClick={() => setPeopleOffset(Math.max(0, peopleOffset - 20))}>
                  Prev
                </button>
                <button type="button" className="rounded border px-2 py-1" disabled={peopleOffset + 20 >= peopleTotal} onClick={() => setPeopleOffset(peopleOffset + 20)}>
                  Next
                </button>
              </div>
            </div>
          </section>
        ) : null}

        {!loading && tab === "Add Teacher" ? (
          <section className="rounded-xl border border-gray-200 bg-white p-4">
            <h2 className="text-lg font-semibold">Add teacher</h2>
            <form className="mt-3 grid gap-3 sm:grid-cols-2" onSubmit={(e) => void submitTeacher(e)}>
              <input aria-label="Teacher name" required className="rounded-md border border-gray-300 px-2 py-1" placeholder="Display name" value={teacherForm.display_name} onChange={(e) => setTeacherForm((prev) => ({ ...prev, display_name: e.target.value }))} />
              <input aria-label="Teacher email" required type="email" className="rounded-md border border-gray-300 px-2 py-1" placeholder="Email" value={teacherForm.email} onChange={(e) => setTeacherForm((prev) => ({ ...prev, email: e.target.value }))} />
              <input aria-label="Employee id" className="rounded-md border border-gray-300 px-2 py-1" placeholder="Employee ID (optional)" value={teacherForm.employee_id} onChange={(e) => setTeacherForm((prev) => ({ ...prev, employee_id: e.target.value }))} />
              <input aria-label="Max weekly hours" className="rounded-md border border-gray-300 px-2 py-1" type="number" min={1} value={teacherForm.max_weekly_hours} onChange={(e) => setTeacherForm((prev) => ({ ...prev, max_weekly_hours: e.target.value }))} />
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={teacherForm.send_invitation} onChange={(e) => setTeacherForm((prev) => ({ ...prev, send_invitation: e.target.checked }))} />
                Send invitation now
              </label>
              <div>
                <button type="submit" className="rounded-md bg-indigo-600 px-3 py-1.5 text-sm text-white">Create teacher</button>
              </div>
            </form>
          </section>
        ) : null}

        {!loading && tab === "Add Parent" ? (
          <section className="rounded-xl border border-gray-200 bg-white p-4">
            <h2 className="text-lg font-semibold">Add parent</h2>
            <form className="mt-3 grid gap-3 sm:grid-cols-2" onSubmit={(e) => void submitParent(e)}>
              <input aria-label="Parent name" required className="rounded-md border border-gray-300 px-2 py-1" placeholder="Display name" value={parentForm.display_name} onChange={(e) => setParentForm((prev) => ({ ...prev, display_name: e.target.value }))} />
              <input aria-label="Parent email" required type="email" className="rounded-md border border-gray-300 px-2 py-1" placeholder="Email" value={parentForm.email} onChange={(e) => setParentForm((prev) => ({ ...prev, email: e.target.value }))} />
              <input aria-label="Parent phone" className="rounded-md border border-gray-300 px-2 py-1" placeholder="Phone (optional)" value={parentForm.phone} onChange={(e) => setParentForm((prev) => ({ ...prev, phone: e.target.value }))} />
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={parentForm.send_invitation} onChange={(e) => setParentForm((prev) => ({ ...prev, send_invitation: e.target.checked }))} />
                Send invitation now
              </label>
              <select aria-label="Initial student" className="rounded-md border border-gray-300 px-2 py-1" value={parentForm.student_id} onChange={(e) => setParentForm((prev) => ({ ...prev, student_id: e.target.value }))}>
                <option value="">No initial relationship</option>
                {studentOptions.map((student) => (
                  <option key={student.person_id} value={student.person_id}>{student.display_name}</option>
                ))}
              </select>
              <select aria-label="Relationship type" className="rounded-md border border-gray-300 px-2 py-1" value={parentForm.relationship_type} onChange={(e) => setParentForm((prev) => ({ ...prev, relationship_type: e.target.value as RelationshipType }))}>
                <option value="mother">mother</option>
                <option value="father">father</option>
                <option value="guardian">guardian</option>
                <option value="sponsor">sponsor</option>
                <option value="other">other</option>
              </select>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={parentForm.is_primary} onChange={(e) => setParentForm((prev) => ({ ...prev, is_primary: e.target.checked }))} />
                Primary contact
              </label>
              <div>
                <button type="submit" className="rounded-md bg-indigo-600 px-3 py-1.5 text-sm text-white">Create parent</button>
              </div>
            </form>
          </section>
        ) : null}

        {!loading && tab === "Add Student" ? (
          <section className="rounded-xl border border-gray-200 bg-white p-4">
            <h2 className="text-lg font-semibold">Add student</h2>
            <form className="mt-3 grid gap-3 sm:grid-cols-2" onSubmit={(e) => void submitStudent(e)}>
              <input aria-label="Student name" required className="rounded-md border border-gray-300 px-2 py-1" placeholder="Name" value={studentForm.name} onChange={(e) => setStudentForm((prev) => ({ ...prev, name: e.target.value }))} />
              <input aria-label="Student code" className="rounded-md border border-gray-300 px-2 py-1" placeholder="Student code" value={studentForm.student_code} onChange={(e) => setStudentForm((prev) => ({ ...prev, student_code: e.target.value }))} />
              <select aria-label="Class" required className="rounded-md border border-gray-300 px-2 py-1" value={studentForm.class_id} onChange={(e) => setStudentForm((prev) => ({ ...prev, class_id: e.target.value }))}>
                <option value="">Select class</option>
                {classOptions.map((klass) => (
                  <option key={klass.id} value={klass.id}>{klass.label}</option>
                ))}
              </select>
              <select aria-label="Optional parent" className="rounded-md border border-gray-300 px-2 py-1" value={studentForm.parent_id} onChange={(e) => setStudentForm((prev) => ({ ...prev, parent_id: e.target.value }))}>
                <option value="">No initial parent relationship</option>
                {parentOptions.map((parent) => (
                  <option key={parent.user_id ?? parent.person_id} value={parent.user_id ?? ""}>{parent.display_name}</option>
                ))}
              </select>
              <select aria-label="Student relationship type" className="rounded-md border border-gray-300 px-2 py-1" value={studentForm.relationship_type} onChange={(e) => setStudentForm((prev) => ({ ...prev, relationship_type: e.target.value as RelationshipType }))}>
                <option value="mother">mother</option>
                <option value="father">father</option>
                <option value="guardian">guardian</option>
                <option value="sponsor">sponsor</option>
                <option value="other">other</option>
              </select>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={studentForm.is_primary} onChange={(e) => setStudentForm((prev) => ({ ...prev, is_primary: e.target.checked }))} />
                Primary contact
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={studentForm.with_enrollment} onChange={(e) => setStudentForm((prev) => ({ ...prev, with_enrollment: e.target.checked }))} />
                Add initial enrollment
              </label>
              {studentForm.with_enrollment ? (
                <input aria-label="Enrollment date" className="rounded-md border border-gray-300 px-2 py-1" type="date" value={studentForm.enrolled_on} onChange={(e) => setStudentForm((prev) => ({ ...prev, enrolled_on: e.target.value }))} />
              ) : <div />}
              <div>
                <button type="submit" className="rounded-md bg-indigo-600 px-3 py-1.5 text-sm text-white">Create student</button>
              </div>
            </form>
          </section>
        ) : null}

        {!loading && tab === "Invitations" ? (
          <section className="rounded-xl border border-gray-200 bg-white p-4">
            <h2 className="text-lg font-semibold">Invitations</h2>
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              <select aria-label="Invitation status" className="rounded-md border border-gray-300 px-2 py-1" value={inviteStatus} onChange={(e) => setInviteStatus(e.target.value as "all" | InvitationStatus)}>
                <option value="all">All statuses</option>
                <option value="pending">pending</option>
                <option value="accepted">accepted</option>
                <option value="revoked">revoked</option>
                <option value="expired">expired</option>
              </select>
              <select aria-label="Invitation role" className="rounded-md border border-gray-300 px-2 py-1" value={inviteRole} onChange={(e) => setInviteRole(e.target.value as "all" | "teacher" | "parent") }>
                <option value="all">All roles</option>
                <option value="teacher">teacher</option>
                <option value="parent">parent</option>
              </select>
            </div>
            <div className="mt-4 overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="text-left text-gray-600">
                    <th className="py-2">Invited email</th>
                    <th>Role</th>
                    <th>State</th>
                    <th>Created</th>
                    <th>Expires</th>
                    <th>Accepted</th>
                    <th>Revoked</th>
                    <th className="text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {inviteRows.map((row) => (
                    <tr key={row.id} className="border-t border-gray-100">
                      <td className="py-2">{row.invited_email}</td>
                      <td>{row.role}</td>
                      <td>{row.status}</td>
                      <td>{formatDate(row.created_at)}</td>
                      <td>{formatDate(row.expires_at)}</td>
                      <td>{formatDate(row.accepted_at)}</td>
                      <td>{formatDate(row.revoked_at)}</td>
                      <td className="text-right">
                        {row.status === "pending" ? (
                          <button type="button" className="rounded border px-2 py-1" onClick={() => void handleRevokeInvitation(row)}>
                            Revoke
                          </button>
                        ) : (
                          <span className="text-gray-500">No action</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-3 text-sm text-gray-600">Total invitations: {inviteTotal}</p>
          </section>
        ) : null}

        {!loading && tab === "Families" ? (
          <section className="space-y-4 rounded-xl border border-gray-200 bg-white p-4">
            <h2 className="text-lg font-semibold">Family relationships</h2>

            <form className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4" onSubmit={(e) => void submitFamilyRelationship(e)}>
              <select aria-label="Family create parent" required className="rounded-md border border-gray-300 px-2 py-1" value={familyCreate.parent_id} onChange={(e) => setFamilyCreate((prev) => ({ ...prev, parent_id: e.target.value }))}>
                <option value="">Select parent</option>
                {parentOptions.map((parent) => (
                  <option key={parent.user_id ?? parent.person_id} value={parent.user_id ?? ""}>{parent.display_name}</option>
                ))}
              </select>
              <select aria-label="Family create student" required className="rounded-md border border-gray-300 px-2 py-1" value={familyCreate.student_id} onChange={(e) => setFamilyCreate((prev) => ({ ...prev, student_id: e.target.value }))}>
                <option value="">Select student</option>
                {studentOptions.map((student) => (
                  <option key={student.person_id} value={student.person_id}>{student.display_name}</option>
                ))}
              </select>
              <select aria-label="Family create relationship type" className="rounded-md border border-gray-300 px-2 py-1" value={familyCreate.relationship_type} onChange={(e) => setFamilyCreate((prev) => ({ ...prev, relationship_type: e.target.value as RelationshipType }))}>
                <option value="mother">mother</option>
                <option value="father">father</option>
                <option value="guardian">guardian</option>
                <option value="sponsor">sponsor</option>
                <option value="other">other</option>
              </select>
              <div className="flex items-center gap-2">
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={familyCreate.is_primary} onChange={(e) => setFamilyCreate((prev) => ({ ...prev, is_primary: e.target.checked }))} />
                  Primary
                </label>
                <button type="submit" className="rounded-md bg-indigo-600 px-3 py-1.5 text-sm text-white">Create</button>
              </div>
            </form>

            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
              Deactivating a relationship may remove parent portal access to the student, while history remains visible.
            </div>

            <div className="grid gap-2 sm:grid-cols-2">
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={familyActiveOnly} onChange={(e) => setFamilyActiveOnly(e.target.checked)} />
                Active only
              </label>
              <select aria-label="Family relationship type filter" className="rounded-md border border-gray-300 px-2 py-1" value={familyTypeFilter} onChange={(e) => setFamilyTypeFilter(e.target.value as "all" | RelationshipType)}>
                <option value="all">All relationship types</option>
                <option value="mother">mother</option>
                <option value="father">father</option>
                <option value="guardian">guardian</option>
                <option value="sponsor">sponsor</option>
                <option value="other">other</option>
              </select>
            </div>

            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="text-left text-gray-600">
                    <th className="py-2">Parent</th>
                    <th>Student</th>
                    <th>Type</th>
                    <th>Primary</th>
                    <th>Active</th>
                    <th>Created</th>
                    <th>Updated</th>
                    <th className="text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredFamilyRows.map((row) => (
                    <tr key={row.relationship_id} className="border-t border-gray-100">
                      <td className="py-2">{row.parent_name}</td>
                      <td>{row.student_name}</td>
                      <td>{row.relationship_type}</td>
                      <td>{row.is_primary ? "yes" : "no"}</td>
                      <td>{row.is_active ? "active" : "inactive"}</td>
                      <td>{formatDate(row.created_at)}</td>
                      <td>{formatDate(row.updated_at)}</td>
                      <td className="text-right">
                        <div className="inline-flex gap-2">
                          <button
                            type="button"
                            className="rounded border px-2 py-1"
                            onClick={() => {
                              const nextType = window.prompt("Relationship type", row.relationship_type);
                              if (!nextType) return;
                              if (!["mother", "father", "guardian", "sponsor", "other"].includes(nextType)) return;
                              void patchFamilyRelationship(row, { relationship_type: nextType as RelationshipType });
                            }}
                          >
                            Change type
                          </button>
                          <button type="button" className="rounded border px-2 py-1" onClick={() => void patchFamilyRelationship(row, { is_primary: !row.is_primary })}>
                            {row.is_primary ? "Unset primary" : "Set primary"}
                          </button>
                          <button type="button" className="rounded border px-2 py-1" onClick={() => void patchFamilyRelationship(row, { is_active: !row.is_active })}>
                            {row.is_active ? "Deactivate" : "Reactivate"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        ) : null}

        {!loading && tab === "Reconciliation" ? (
          <section className="rounded-xl border border-gray-200 bg-white p-4">
            <h2 className="text-lg font-semibold">Reconciliation diagnostics</h2>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <article className="rounded-lg border border-gray-200 p-3">
                <h3 className="font-medium">People issues</h3>
                <ul className="mt-2 space-y-1 text-sm text-gray-700">
                  <li>Teachers without User: {peopleSummary?.teachers_without_user_accounts ?? 0}</li>
                  <li>Parents without User: {peopleSummary?.parents_without_user_accounts ?? 0}</li>
                  <li>Users without required role profile: {peopleSummary?.users_without_matching_role_profiles ?? 0}</li>
                  <li>Inactive User with active profile: {peopleSummary?.inactive_users_with_active_profiles ?? 0}</li>
                  <li>Expired pending invitation: {peopleSummary?.expired_invitations ?? 0}</li>
                </ul>
                <p className="mt-2 text-xs text-gray-500">Use People filters and invitation actions to resolve.</p>
              </article>
              <article className="rounded-lg border border-gray-200 p-3">
                <h3 className="font-medium">Family issues</h3>
                <ul className="mt-2 space-y-1 text-sm text-gray-700">
                  <li>Students without active relationship: {familySummary?.students_with_no_active_parent_guardian_relationship ?? 0}</li>
                  <li>Students with multiple relationships: {familySummary?.students_with_multiple_active_relationships ?? 0}</li>
                  <li>Inactive historical relationships: {familySummary?.inactive_historical_relationships ?? 0}</li>
                  <li>Cross-tenant inconsistencies: {familySummary?.cross_tenant_inconsistencies ?? 0}</li>
                </ul>
                <p className="mt-2 text-xs text-gray-500">Use Families create/update actions to resolve.</p>
              </article>
            </div>
          </section>
        ) : null}
      </main>
    </RoleGuard>
  );
}
