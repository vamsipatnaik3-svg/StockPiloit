
"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

const API_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type Role = "OWNER" | "MANAGER" | "STAFF" | "ANALYST";

type UserProfile = {
  user_id: string;
  full_name: string;
  email: string;
  company_id: string;
  company_name: string;
  role: Role;
};

type Branch = {
  id: string;
  company_id: string;
  name: string;
  code: string | null;
  address_line1: string | null;
  address_line2: string | null;
  city: string | null;
  state: string | null;
  postal_code: string | null;
  country_code: string;
  timezone: string;
  is_active: boolean;
  created_at: string;
};

type BranchMember = {
  id: string;
  branch_id: string;
  company_membership_id: string;
  user_id: string;
  full_name: string;
  email: string;
  role: Role;
  created_at: string;
};

type EligibleMember = {
  membership_id: string;
  user_id: string;
  full_name: string;
  email: string;
  role: Role;
};

type BranchForm = {
  name: string;
  code: string;
  address_line1: string;
  address_line2: string;
  city: string;
  state: string;
  postal_code: string;
  country_code: string;
  timezone: string;
};

const emptyBranchForm: BranchForm = {
  name: "",
  code: "",
  address_line1: "",
  address_line2: "",
  city: "",
  state: "",
  postal_code: "",
  country_code: "IN",
  timezone: "Asia/Kolkata",
};

async function getErrorMessage(response: Response): Promise<string> {
  try {
    const data = await response.json();
    return data.detail || "Something went wrong. Please try again.";
  } catch {
    return "Something went wrong. Please try again.";
  }
}

function roleLabel(role: Role): string {
  return {
    OWNER: "Owner",
    MANAGER: "Manager",
    STAFF: "Staff",
    ANALYST: "Analyst",
  }[role];
}

export default function BranchesPage() {
  const router = useRouter();

  const [user, setUser] = useState<UserProfile | null>(null);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [selectedBranchId, setSelectedBranchId] = useState("");

  const [members, setMembers] = useState<BranchMember[]>([]);
  const [eligibleMembers, setEligibleMembers] = useState<EligibleMember[]>([]);
  const [selectedMemberId, setSelectedMemberId] = useState("");

  const [form, setForm] = useState<BranchForm>(emptyBranchForm);
  const [showCreateForm, setShowCreateForm] = useState(false);

  const [loading, setLoading] = useState(true);
  const [membersLoading, setMembersLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [assigning, setAssigning] = useState(false);
  const [removingId, setRemovingId] = useState("");

  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const isOwner = user?.role === "OWNER";

  const selectedBranch =
    branches.find((branch) => branch.id === selectedBranchId) || null;

  const assignedMembershipIds = new Set(
    members.map((member) => member.company_membership_id)
  );

  const availableMembers = eligibleMembers.filter(
    (member) => !assignedMembershipIds.has(member.membership_id)
  );

  const loadWorkspace = useCallback(async () => {
    setLoading(true);
    setError("");

    try {
      const profileResponse = await fetch(`${API_URL}/api/v1/auth/me`, {
        credentials: "include",
      });

      if (profileResponse.status === 401) {
        router.replace("/login");
        return;
      }

      if (!profileResponse.ok) {
        throw new Error(await getErrorMessage(profileResponse));
      }

      const profile: UserProfile = await profileResponse.json();
      setUser(profile);

      const branchResponse = await fetch(`${API_URL}/api/v1/branches`, {
        credentials: "include",
      });

      if (branchResponse.status === 401) {
        router.replace("/login");
        return;
      }

      if (!branchResponse.ok) {
        throw new Error(await getErrorMessage(branchResponse));
      }

      const branchData: Branch[] = await branchResponse.json();
      setBranches(branchData);

      setSelectedBranchId((current) => {
        if (current && branchData.some((branch) => branch.id === current)) {
          return current;
        }

        return branchData[0]?.id || "";
      });

      if (profile.role === "OWNER") {
        const eligibleResponse = await fetch(
          `${API_URL}/api/v1/branches/members/eligible`,
          { credentials: "include" }
        );

        if (!eligibleResponse.ok) {
          throw new Error(await getErrorMessage(eligibleResponse));
        }

        const eligibleData: EligibleMember[] =
          await eligibleResponse.json();

        setEligibleMembers(eligibleData);
      } else {
        setEligibleMembers([]);
      }
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to load branch information."
      );
    } finally {
      setLoading(false);
    }
  }, [router]);

  const loadBranchMembers = useCallback(async (branchId: string) => {
    if (!branchId) {
      setMembers([]);
      return;
    }

    setMembersLoading(true);
    setError("");

    try {
      const response = await fetch(
        `${API_URL}/api/v1/branches/${branchId}/members`,
        { credentials: "include" }
      );

      if (response.status === 401) {
        router.replace("/login");
        return;
      }

      if (!response.ok) {
        throw new Error(await getErrorMessage(response));
      }

      const data: BranchMember[] = await response.json();
      setMembers(data);
    } catch (err) {
      setMembers([]);
      setError(
        err instanceof Error
          ? err.message
          : "Unable to load branch members."
      );
    } finally {
      setMembersLoading(false);
    }
  }, [router]);

  useEffect(() => {
  async function initializeWorkspace() {
    await loadWorkspace();
  }

  void initializeWorkspace();
}, [loadWorkspace]);

useEffect(() => {
  if (!selectedBranchId) return;

  async function initializeMembers() {
    await loadBranchMembers(selectedBranchId);
  }

  void initializeMembers();
}, [selectedBranchId, loadBranchMembers]);

  function updateForm(field: keyof BranchForm, value: string) {
    setForm((current) => ({
      ...current,
      [field]: value,
    }));
  }

  async function handleCreateBranch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setSuccess("");

    try {
      const payload = {
        name: form.name.trim(),
        code: form.code.trim() || null,
        address_line1: form.address_line1.trim() || null,
        address_line2: form.address_line2.trim() || null,
        city: form.city.trim() || null,
        state: form.state.trim() || null,
        postal_code: form.postal_code.trim() || null,
        country_code: form.country_code.trim().toUpperCase(),
        timezone: form.timezone.trim(),
      };

      const response = await fetch(`${API_URL}/api/v1/branches`, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      if (response.status === 401) {
        router.replace("/login");
        return;
      }

      if (!response.ok) {
        throw new Error(await getErrorMessage(response));
      }

      const createdBranch: Branch = await response.json();

      setBranches((current) =>
        [...current, createdBranch].sort((a, b) =>
          a.name.localeCompare(b.name)
        )
      );

      setSelectedBranchId(createdBranch.id);
      setForm(emptyBranchForm);
      setShowCreateForm(false);
      setSuccess("Branch created successfully.");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Unable to create branch."
      );
    } finally {
      setSaving(false);
    }
  }

  async function handleAssignMember() {
    if (!selectedBranchId || !selectedMemberId) return;

    setAssigning(true);
    setError("");
    setSuccess("");

    try {
      const response = await fetch(
        `${API_URL}/api/v1/branches/${selectedBranchId}/members`,
        {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            company_membership_id: selectedMemberId,
          }),
        }
      );

      if (response.status === 401) {
        router.replace("/login");
        return;
      }

      if (!response.ok) {
        throw new Error(await getErrorMessage(response));
      }

      const newMember: BranchMember = await response.json();

      setMembers((current) =>
        [...current, newMember].sort((a, b) =>
          a.full_name.localeCompare(b.full_name)
        )
      );

      setSelectedMemberId("");
      setSuccess("Member assigned successfully.");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Unable to assign member."
      );
    } finally {
      setAssigning(false);
    }
  }

  async function handleRemoveMember(membershipId: string) {
    if (!selectedBranchId) return;

    const confirmed = window.confirm(
      "Remove this member from the selected branch?"
    );

    if (!confirmed) return;

    setRemovingId(membershipId);
    setError("");
    setSuccess("");

    try {
      const response = await fetch(
        `${API_URL}/api/v1/branches/${selectedBranchId}/members/${membershipId}`,
        {
          method: "DELETE",
          credentials: "include",
        }
      );

      if (response.status === 401) {
        router.replace("/login");
        return;
      }

      if (!response.ok) {
        throw new Error(await getErrorMessage(response));
      }

      setMembers((current) =>
        current.filter(
          (member) => member.company_membership_id !== membershipId
        )
      );

      setSuccess("Member removed from the branch.");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Unable to remove member."
      );
    } finally {
      setRemovingId("");
    }
  }

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[#f5f7fb]">
        <div className="text-center">
          <div className="mx-auto h-10 w-10 animate-spin rounded-full border-4 border-blue-100 border-t-blue-600" />
          <p className="mt-4 text-sm font-medium text-slate-500">
            Loading branch workspace...
          </p>
        </div>
      </main>
    );
  }

  if (!user) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[#f5f7fb] p-6">
        <div className="max-w-md rounded-2xl border border-slate-200 bg-white p-8 text-center">
          <h1 className="text-lg font-bold text-slate-900">
            Branch workspace unavailable
          </h1>
          <p className="mt-3 text-sm text-slate-500">
            {error || "Unable to load your account."}
          </p>
          <Link
            href="/dashboard"
            className="mt-6 inline-block rounded-xl bg-blue-600 px-5 py-3 text-sm font-semibold text-white"
          >
            Return to dashboard
          </Link>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-[#f5f7fb] text-slate-900">
      <header className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-200 bg-white px-5 py-5 sm:px-8">
        <div>
          <Link
            href="/dashboard"
            className="text-xs font-semibold text-blue-600 hover:text-blue-800"
          >
            ← Back to dashboard
          </Link>
          <h1 className="mt-2 text-2xl font-bold tracking-tight">
            Branch management
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            Manage your business locations and branch teams.
          </p>
        </div>

        <div className="rounded-xl border border-blue-100 bg-blue-50 px-4 py-2">
          <p className="text-xs font-semibold text-blue-700">
            {user.company_name}
          </p>
          <p className="mt-1 text-[11px] text-blue-600">
            {roleLabel(user.role)}
          </p>
        </div>
      </header>

      <div className="mx-auto max-w-[1400px] px-5 py-8 sm:px-8">
        {error && (
          <div
            role="alert"
            className="mb-5 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
          >
            {error}
          </div>
        )}

        {success && (
          <div
            role="status"
            className="mb-5 rounded-xl border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700"
          >
            {success}
          </div>
        )}

        <div className="grid gap-6 lg:grid-cols-[340px_minmax(0,1fr)]">
          {/* BRANCH LIST */}
          <aside className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-base font-bold">Your branches</h2>
                <p className="mt-1 text-xs text-slate-500">
                  {branches.length} location{branches.length === 1 ? "" : "s"}
                </p>
              </div>

              {isOwner && (
                <button
                  onClick={() => {
                    setShowCreateForm((current) => !current);
                    setError("");
                    setSuccess("");
                  }}
                  className="rounded-lg bg-blue-600 px-3 py-2 text-xs font-semibold text-white hover:bg-blue-700"
                >
                  {showCreateForm ? "Cancel" : "+ Add branch"}
                </button>
              )}
            </div>

            <div className="mt-5 space-y-2">
              {branches.length === 0 ? (
                <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 p-5 text-center">
                  <p className="text-sm font-semibold text-slate-700">
                    No branches yet
                  </p>
                  <p className="mt-2 text-xs leading-5 text-slate-500">
                    {isOwner
                      ? "Create your first branch to start organizing your locations."
                      : "You have not been assigned to an active branch yet."}
                  </p>
                </div>
              ) : (
                branches.map((branch) => (
                  <button
                    key={branch.id}
                    onClick={() => {
                      setSelectedBranchId(branch.id);
                      setError("");
                      setSuccess("");
                    }}
                    className={`w-full rounded-xl border p-4 text-left transition ${
                      selectedBranchId === branch.id
                        ? "border-blue-200 bg-blue-50"
                        : "border-slate-100 bg-white hover:border-slate-300 hover:bg-slate-50"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold text-slate-800">
                          {branch.name}
                        </p>
                        <p className="mt-1 text-xs text-slate-500">
                          {branch.code || "No branch code"}
                        </p>
                      </div>
                      <span
                        className={`shrink-0 rounded-full px-2 py-1 text-[10px] font-semibold ${
                          branch.is_active
                            ? "bg-green-50 text-green-700"
                            : "bg-slate-100 text-slate-500"
                        }`}
                      >
                        {branch.is_active ? "Active" : "Inactive"}
                      </span>
                    </div>

                    <p className="mt-3 truncate text-xs text-slate-500">
                      {[branch.city, branch.state, branch.country_code]
                        .filter(Boolean)
                        .join(", ") || "Location not specified"}
                    </p>
                  </button>
                ))
              )}
            </div>
          </aside>

          {/* MAIN PANEL */}
          <section className="min-w-0 space-y-6">
            {showCreateForm && isOwner && (
              <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
                <div className="mb-5">
                  <h2 className="text-base font-bold">Create a branch</h2>
                  <p className="mt-1 text-xs text-slate-500">
                    Add a new location to your company workspace.
                  </p>
                </div>

                <form onSubmit={handleCreateBranch} className="space-y-5">
                  <div className="grid gap-4 sm:grid-cols-2">
                    <Field
                      label="Branch name *"
                      value={form.name}
                      onChange={(value) => updateForm("name", value)}
                      placeholder="e.g. Hyderabad Main Branch"
                      required
                    />
                    <Field
                      label="Branch code"
                      value={form.code}
                      onChange={(value) => updateForm("code", value)}
                      placeholder="e.g. HYD01"
                    />
                    <Field
                      label="Address line 1"
                      value={form.address_line1}
                      onChange={(value) => updateForm("address_line1", value)}
                      placeholder="Street address"
                    />
                    <Field
                      label="Address line 2"
                      value={form.address_line2}
                      onChange={(value) => updateForm("address_line2", value)}
                      placeholder="Apartment, suite, etc."
                    />
                    <Field
                      label="City"
                      value={form.city}
                      onChange={(value) => updateForm("city", value)}
                      placeholder="City"
                    />
                    <Field
                      label="State"
                      value={form.state}
                      onChange={(value) => updateForm("state", value)}
                      placeholder="State"
                    />
                    <Field
                      label="Postal code"
                      value={form.postal_code}
                      onChange={(value) => updateForm("postal_code", value)}
                      placeholder="Postal code"
                    />
                    <Field
                      label="Country code *"
                      value={form.country_code}
                      onChange={(value) => updateForm("country_code", value)}
                      placeholder="IN"
                      required
                    />
                    <div className="sm:col-span-2">
                      <Field
                        label="Timezone *"
                        value={form.timezone}
                        onChange={(value) => updateForm("timezone", value)}
                        placeholder="Asia/Kolkata"
                        required
                      />
                      <p className="mt-1 text-[11px] text-slate-400">
                        Use an IANA timezone, such as Asia/Kolkata or
                        Europe/London.
                      </p>
                    </div>
                  </div>

                  <div className="flex flex-wrap justify-end gap-3 border-t border-slate-100 pt-4">
                    <button
                      type="button"
                      onClick={() => setShowCreateForm(false)}
                      className="rounded-xl border border-slate-200 px-5 py-2.5 text-sm font-semibold text-slate-600 hover:bg-slate-50"
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      disabled={saving}
                      className="rounded-xl bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
                    >
                      {saving ? "Creating..." : "Create branch"}
                    </button>
                  </div>
                </form>
              </section>
            )}

            {selectedBranch ? (
              <>
                {/* SELECTED BRANCH DETAILS */}
                <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div>
                      <p className="text-xs font-bold uppercase tracking-wider text-blue-600">
                        SELECTED LOCATION
                      </p>
                      <h2 className="mt-2 text-xl font-bold">
                        {selectedBranch.name}
                      </h2>
                      <p className="mt-1 text-sm text-slate-500">
                        {selectedBranch.code || "No branch code"}
                      </p>
                    </div>

                    <span
                      className={`rounded-full px-3 py-1.5 text-xs font-semibold ${
                        selectedBranch.is_active
                          ? "bg-green-50 text-green-700"
                          : "bg-slate-100 text-slate-500"
                      }`}
                    >
                      {selectedBranch.is_active ? "Active" : "Inactive"}
                    </span>
                  </div>

                  <div className="mt-6 grid gap-4 border-t border-slate-100 pt-5 sm:grid-cols-2">
                    <div>
                      <p className="text-xs text-slate-400">Address</p>
                      <p className="mt-1 text-sm font-medium text-slate-700">
                        {[
                          selectedBranch.address_line1,
                          selectedBranch.address_line2,
                          selectedBranch.city,
                          selectedBranch.state,
                          selectedBranch.postal_code,
                          selectedBranch.country_code,
                        ]
                          .filter(Boolean)
                          .join(", ") || "Not specified"}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-slate-400">Timezone</p>
                      <p className="mt-1 text-sm font-medium text-slate-700">
                        {selectedBranch.timezone}
                      </p>
                    </div>
                  </div>
                </section>

                {/* BRANCH MEMBERS */}
                <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <h2 className="text-base font-bold">Branch team</h2>
                      <p className="mt-1 text-xs text-slate-500">
                        {members.length} assigned member
                        {members.length === 1 ? "" : "s"}
                      </p>
                    </div>
                  </div>

                  {isOwner && (
                    <div className="mt-5 rounded-xl border border-blue-100 bg-blue-50/50 p-4">
                      <p className="text-sm font-semibold text-slate-800">
                        Assign a team member
                      </p>
                      <p className="mt-1 text-xs text-slate-500">
                        Select an active member from your company.
                      </p>

                      <div className="mt-3 flex flex-col gap-3 sm:flex-row">
                        <select
                          value={selectedMemberId}
                          onChange={(event) =>
                            setSelectedMemberId(event.target.value)
                          }
                          className="min-w-0 flex-1 rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                        >
                          <option value="">Select a team member</option>
                          {availableMembers.map((member) => (
                            <option
                              key={member.membership_id}
                              value={member.membership_id}
                            >
                              {member.full_name} · {roleLabel(member.role)} ·{" "}
                              {member.email}
                            </option>
                          ))}
                        </select>

                        <button
                          onClick={() => void handleAssignMember()}
                          disabled={!selectedMemberId || assigning}
                          className="rounded-xl bg-blue-600 px-5 py-3 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {assigning ? "Assigning..." : "Assign member"}
                        </button>
                      </div>

                      {availableMembers.length === 0 && (
                        <p className="mt-3 text-xs text-slate-500">
                          No unassigned active company members are available.
                        </p>
                      )}
                    </div>
                  )}

                  {membersLoading ? (
                    <div className="py-12 text-center text-sm text-slate-400">
                      Loading branch members...
                    </div>
                  ) : members.length === 0 ? (
                    <div className="mt-5 rounded-xl border border-dashed border-slate-200 bg-slate-50 px-5 py-10 text-center">
                      <h3 className="text-sm font-semibold text-slate-700">
                        No members assigned
                      </h3>
                      <p className="mt-2 text-xs text-slate-500">
                        {isOwner
                          ? "Assign employees to this branch to give them access."
                          : "There are currently no members assigned to this branch."}
                      </p>
                    </div>
                  ) : (
                    <div className="mt-5 overflow-x-auto">
                      <table className="w-full min-w-[520px] text-left">
                        <thead>
                          <tr className="border-b border-slate-100 text-[10px] font-bold uppercase tracking-wider text-slate-400">
                            <th className="pb-3 pr-4">Team member</th>
                            <th className="pb-3 pr-4">Role</th>
                            {isOwner && (
                              <th className="pb-3 text-right">Action</th>
                            )}
                          </tr>
                        </thead>
                        <tbody>
                          {members.map((member) => (
                            <tr
                              key={member.id}
                              className="border-b border-slate-50 last:border-0"
                            >
                              <td className="py-4 pr-4">
                                <p className="text-sm font-semibold text-slate-800">
                                  {member.full_name}
                                </p>
                                <p className="mt-1 text-xs text-slate-500">
                                  {member.email}
                                </p>
                              </td>
                              <td className="py-4 pr-4">
                                <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">
                                  {roleLabel(member.role)}
                                </span>
                              </td>
                              {isOwner && (
                                <td className="py-4 text-right">
                                  <button
                                    onClick={() =>
                                      void handleRemoveMember(
                                        member.company_membership_id
                                      )
                                    }
                                    disabled={
                                      removingId ===
                                      member.company_membership_id
                                    }
                                    className="text-xs font-semibold text-red-600 hover:text-red-800 disabled:opacity-50"
                                  >
                                    {removingId ===
                                    member.company_membership_id
                                      ? "Removing..."
                                      : "Remove"}
                                  </button>
                                </td>
                              )}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </section>
              </>
            ) : (
              <section className="flex min-h-80 flex-col items-center justify-center rounded-2xl border border-dashed border-slate-200 bg-white p-8 text-center">
                <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-blue-50 text-2xl text-blue-600">
                  ⌂
                </div>
                <h2 className="mt-5 text-lg font-bold text-slate-800">
                  {branches.length === 0
                    ? "Your branch workspace is ready"
                    : "Select a branch"}
                </h2>
                <p className="mt-2 max-w-sm text-sm leading-6 text-slate-500">
                  {branches.length === 0
                    ? isOwner
                      ? "Create your first branch to start managing locations and team assignments."
                      : "You will see branch details here once you are assigned to a branch."
                    : "Choose a location from the branch list to view its details and team."}
                </p>
                {isOwner && branches.length === 0 && (
                  <button
                    onClick={() => setShowCreateForm(true)}
                    className="mt-5 rounded-xl bg-blue-600 px-5 py-3 text-sm font-semibold text-white hover:bg-blue-700"
                  >
                    + Create your first branch
                  </button>
                )}
              </section>
            )}
          </section>
        </div>

        <footer className="mt-10 border-t border-slate-200 pt-5 text-xs text-slate-400">
          © 2026 Tavuno · Retail Intelligence
        </footer>
      </div>
    </main>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
  required = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  required?: boolean;
}) {
  return (
    <label className="block">
      <span className="mb-2 block text-xs font-semibold text-slate-600">
        {label}
      </span>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        required={required}
        className="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm outline-none transition placeholder:text-slate-300 focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
      />
    </label>
  );
}
