
"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

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
  must_change_password: boolean;
};

type Branch = {
  id: string;
  name: string;
  code: string | null;
  is_active: boolean;
};

async function getErrorMessage(response: Response): Promise<string> {
  try {
    const data = await response.json();

    if (typeof data.detail === "string") {
      return data.detail;
    }

    if (Array.isArray(data.detail)) {
      return data.detail.map((item: { msg?: string }) => item.msg || "Invalid input").join(", ");
    }

    return "Something went wrong. Please try again.";
  } catch {
    return "Something went wrong. Please try again.";
  }
}

export default function TeamPage() {
  const router = useRouter();

  const [branches, setBranches] = useState<Branch[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [temporaryPassword, setTemporaryPassword] = useState("");
  const [role, setRole] = useState<"MANAGER" | "STAFF" | "ANALYST">("MANAGER");
  const [selectedBranchIds, setSelectedBranchIds] = useState<string[]>([]);

  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function loadWorkspace() {
      try {
        const profileResponse = await fetch(
          `${API_URL}/api/v1/auth/me`,
          { credentials: "include" }
        );

        if (profileResponse.status === 401) {
          router.replace("/login");
          return;
        }

        if (!profileResponse.ok) {
          throw new Error(await getErrorMessage(profileResponse));
        }

        const profile: UserProfile = await profileResponse.json();

        if (profile.must_change_password) {
          router.replace("/change-password");
          return;
        }

        if (profile.role !== "OWNER") {
          router.replace("/dashboard");
          return;
        }

        const branchResponse = await fetch(
          `${API_URL}/api/v1/branches`,
          { credentials: "include" }
        );

        if (branchResponse.status === 401) {
          router.replace("/login");
          return;
        }

        if (!branchResponse.ok) {
          throw new Error(await getErrorMessage(branchResponse));
        }

        const branchData: Branch[] = await branchResponse.json();

        if (!cancelled) {
          setBranches(branchData.filter((branch) => branch.is_active));
        }
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error
              ? err.message
              : "Unable to load team workspace."
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void loadWorkspace();

    return () => {
      cancelled = true;
    };
  }, [router]);

  function toggleBranch(branchId: string) {
    setSelectedBranchIds((current) =>
      current.includes(branchId)
        ? current.filter((id) => id !== branchId)
        : [...current, branchId]
    );
  }

  async function handleCreateEmployee(
    event: React.FormEvent<HTMLFormElement>
  ) {
    event.preventDefault();

    setError("");
    setSuccess("");

    if (selectedBranchIds.length === 0) {
      setError("Please assign at least one branch.");
      return;
    }

    if (temporaryPassword.length < 12) {
      setError("Temporary password must contain at least 12 characters.");
      return;
    }

    setSaving(true);

    try {
      const payload = {
        full_name: fullName.trim(),
        email: email.trim().toLowerCase(),
        temporary_password: temporaryPassword,
        role,
        branch_ids: selectedBranchIds,
      };

      const response = await fetch(
        `${API_URL}/api/v1/team/employees`,
        {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify(payload),
        }
      );

      if (response.status === 401) {
        router.replace("/login");
        return;
      }

      if (!response.ok) {
        throw new Error(await getErrorMessage(response));
      }

      setSuccess(
        `${fullName.trim()} was created successfully as ${role}. They must change their temporary password at first login.`
      );

      setFullName("");
      setEmail("");
      setTemporaryPassword("");
      setRole("MANAGER");
      setSelectedBranchIds([]);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to create employee."
      );
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[#f5f7fb]">
        <p className="text-sm font-medium text-slate-500">
          Loading team workspace...
        </p>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-[#f5f7fb] text-slate-900">
      <header className="border-b border-slate-200 bg-white px-5 py-6 sm:px-8">
        <div className="mx-auto max-w-5xl">
          <Link
            href="/dashboard"
            className="text-xs font-semibold text-blue-600 hover:text-blue-800"
          >
            ← Back to dashboard
          </Link>

          <h1 className="mt-3 text-2xl font-bold">
            Team Management
          </h1>

          <p className="mt-2 text-sm text-slate-500">
            Create employees, assign roles and manage branch access.
          </p>
        </div>
      </header>

      <div className="mx-auto max-w-5xl px-5 py-8 sm:px-8">
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

        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
          <div className="mb-7">
            <h2 className="text-lg font-bold">
              Add a team member
            </h2>
            <p className="mt-2 text-sm text-slate-500">
              Create an employee account for your company.
            </p>
          </div>

          <form onSubmit={handleCreateEmployee} className="space-y-6">
            <div className="grid gap-5 sm:grid-cols-2">
              <div>
                <label className="mb-2 block text-xs font-semibold text-slate-600">
                  Full name *
                </label>
                <input
                  required
                  minLength={2}
                  maxLength={150}
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  placeholder="Enter employee name"
                  className="w-full rounded-xl border border-slate-200 px-4 py-3 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                />
              </div>

              <div>
                <label className="mb-2 block text-xs font-semibold text-slate-600">
                  Email address *
                </label>
                <input
                  required
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="employee@company.com"
                  className="w-full rounded-xl border border-slate-200 px-4 py-3 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                />
              </div>

              <div>
                <label className="mb-2 block text-xs font-semibold text-slate-600">
                  Temporary password *
                </label>
                <input
                  required
                  type="password"
                  minLength={12}
                  maxLength={128}
                  value={temporaryPassword}
                  onChange={(e) => setTemporaryPassword(e.target.value)}
                  placeholder="Minimum 12 characters"
                  className="w-full rounded-xl border border-slate-200 px-4 py-3 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                />
                <p className="mt-2 text-xs text-slate-400">
                  The employee must change this password at first login.
                </p>
              </div>

              <div>
                <label className="mb-2 block text-xs font-semibold text-slate-600">
                  Employee role *
                </label>
                <select
                  value={role}
                  onChange={(e) =>
                    setRole(e.target.value as "MANAGER" | "STAFF" | "ANALYST")
                  }
                  className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                >
                  <option value="MANAGER">Manager</option>
                  <option value="STAFF">Staff</option>
                  <option value="ANALYST">Analyst</option>
                </select>
              </div>
            </div>

            <div className="border-t border-slate-100 pt-6">
              <h3 className="text-sm font-bold">
                Assign branches *
              </h3>
              <p className="mt-1 text-xs text-slate-500">
                Select the branches this employee can access.
              </p>

              {branches.length === 0 ? (
                <div className="mt-4 rounded-xl border border-dashed border-slate-200 bg-slate-50 p-5">
                  <p className="text-sm font-medium text-slate-700">
                    No active branches available.
                  </p>
                  <Link
                    href="/dashboard/branches"
                    className="mt-2 inline-block text-xs font-semibold text-blue-600 hover:text-blue-800"
                  >
                    Create a branch first →
                  </Link>
                </div>
              ) : (
                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                  {branches.map((branch) => (
                    <label
                      key={branch.id}
                      className={`flex cursor-pointer items-center gap-3 rounded-xl border p-4 transition ${
                        selectedBranchIds.includes(branch.id)
                          ? "border-blue-300 bg-blue-50"
                          : "border-slate-200 hover:bg-slate-50"
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={selectedBranchIds.includes(branch.id)}
                        onChange={() => toggleBranch(branch.id)}
                        className="h-4 w-4 accent-blue-600"
                      />
                      <span>
                        <span className="block text-sm font-semibold text-slate-800">
                          {branch.name}
                        </span>
                        <span className="mt-1 block text-xs text-slate-500">
                          {branch.code || "No branch code"}
                        </span>
                      </span>
                    </label>
                  ))}
                </div>
              )}

              <p className="mt-3 text-xs text-slate-400">
                {selectedBranchIds.length} branch(es) selected
              </p>
            </div>

            <div className="flex flex-wrap items-center justify-end gap-3 border-t border-slate-100 pt-6">
              <button
                type="button"
                onClick={() => router.push("/dashboard")}
                className="rounded-xl border border-slate-200 px-5 py-3 text-sm font-semibold text-slate-600 hover:bg-slate-50"
              >
                Cancel
              </button>

              <button
                type="submit"
                disabled={saving || branches.length === 0}
                className="rounded-xl bg-blue-600 px-6 py-3 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {saving ? "Creating employee..." : "Create employee"}
              </button>
            </div>
          </form>
        </div>

        <p className="mt-5 text-xs leading-5 text-slate-400">
          Share temporary credentials through a secure channel. Do not send
          passwords through ordinary unencrypted email.
        </p>
      </div>
    </main>
  );
}
