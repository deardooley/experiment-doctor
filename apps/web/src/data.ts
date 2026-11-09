export interface Point {
  t: number;
  x: number;
}
const decimal = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i;
export const uuid =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function parseTrajectory(text: string): Point[] {
  if (new TextEncoder().encode(text).length > 524288)
    throw new Error("Trajectory exceeds the bounded plot limit.");
  const rows = text.trim().split(/\r?\n/);
  if (rows.shift() !== "t,x" || rows.length < 2 || rows.length > 20000)
    throw new Error("Trajectory is not a bounded t,x CSV.");
  const result: Point[] = [];
  for (const row of rows) {
    const cells = row.split(",");
    if (cells.length !== 2 || !cells.every((cell) => decimal.test(cell.trim())))
      throw new Error("Trajectory contains invalid numeric data.");
    const [t, x] = cells.map(Number);
    if (
      !Number.isFinite(t) ||
      !Number.isFinite(x) ||
      t < 0 ||
      t > 5.00000001 ||
      Math.abs(x) > 1e6 ||
      (result.length > 0 && t <= result.at(-1)!.t)
    ) {
      throw new Error(
        "Trajectory is outside the safe plotting bounds. Download the raw evidence for inspection.",
      );
    }
    result.push({ t, x });
  }
  return result;
}

export function sampled(points: Point[], maximum = 800): Point[] {
  const step = Math.max(1, Math.ceil(points.length / maximum));
  const result = points.filter((_, index) => index % step === 0);
  if (result.at(-1) !== points.at(-1)) result.push(points.at(-1)!);
  return result;
}

export function nearest(points: Point[], t: number): Point | undefined {
  if (!points.length) return;
  let left = 0,
    right = points.length - 1;
  while (left < right) {
    const middle = (left + right) >>> 1;
    if (points[middle].t < t) left = middle + 1;
    else right = middle;
  }
  return left > 0 &&
    Math.abs(points[left - 1].t - t) < Math.abs(points[left].t - t)
    ? points[left - 1]
    : points[left];
}

export function metric(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  if (value === 0) return "0";
  return Math.abs(value) < 0.0001 || Math.abs(value) >= 10000
    ? value.toExponential(2)
    : Number(value.toPrecision(5)).toString();
}

const labels: Record<string, string> = {
  binding: "Evidence & parameter binding",
  valid_numeric: "Finite numeric data",
  time_grid: "Time grid & endpoint",
  initial_value: "Initial concentration",
  nonnegative: "Nonnegative concentration",
  nonincreasing: "Nonincreasing decay",
  analytic_error: "Maximum analytical error",
  convergence: "Refinement convergence",
  present: "Required evidence",
};
export function checkLabel(key: string): string {
  return labels[key.split(".").at(-1)!] ?? key;
}
export function bytes(size: number): string {
  return size < 1024
    ? `${size} B`
    : size < 1024 * 1024
      ? `${(size / 1024).toFixed(1)} KB`
      : `${(size / 1024 / 1024).toFixed(1)} MB`;
}
export function eventLabel(
  kind: string,
  data: Record<string, unknown>,
): string | null {
  if (kind === "QUEUED") return "Experiment accepted into the queue";
  if (kind === "RUNNING") return "Isolated execution started";
  if (kind === "ATTEMPT_STARTED")
    return Number(data.revision) === 0
      ? "Original experiment"
      : `Candidate revision ${data.revision}`;
  if (kind === "MODEL_REQUESTED") return "Diagnosis requested from the model";
  if (kind === "PATCH_AUTHORIZED")
    return "Patch passed the allowed-change policy";
  if (kind === "VERIFICATION_COMPLETED")
    return `Independent checks: ${data.verdict} · ${data.checks_passed}/${data.checks_total} passed`;
  if (kind === "CONTAINMENT_DENIED")
    return "Network connections denied by the sandbox";
  if (kind === "HEALTHY_AFTER_CONTAINMENT")
    return "Healthy computation completed after containment";
  if (kind === "CANCEL_REQUESTED") return "Cancellation requested";
  if (kind === "EVIDENCE_EXPIRED") return "Evidence retention expired";
  if (kind === "TOOL" && data.tool === "submit_job") {
    const role: Record<string, string> = {
      primary: "Primary simulation submitted",
      refinement: "Refinement simulation submitted",
      held_out: "Held-out simulation submitted",
      verification: "Trusted verification submitted",
    };
    return role[String(data.role)] ?? "Constrained job submitted";
  }
  if (
    [
      "VERIFIED_REPAIR",
      "VERIFIED_HEALTHY",
      "NOT_REPAIRED",
      "INCOMPLETE",
      "CANCELLED",
      "BLOCKED",
      "UNVERIFIED",
      "CONTAINED",
      "NOT_CONTAINED",
    ].includes(kind)
  )
    return "Report finalized";
  return null;
}
