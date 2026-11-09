import { useEffect, useState, useRef } from "react";
import { createRoot } from "react-dom/client";
import { api, trajectory, downloadBundle, downloadArtifact } from "./api";
import {
  metric,
  sampled,
  nearest,
  eventLabel,
  checkLabel,
  bytes,
  uuid,
} from "./data";
import type { Point } from "./data";
import type {
  ExperimentView,
  EventView,
  AppView,
  ExperimentSummary,
} from "./generated/contracts";
import "./style.css";
const titles: Record<string, string> = {
  "decay-coarse-step": "An unstable time step",
  "decay-wrong-sign": "Decay that grows",
  "decay-healthy": "A healthy control",
};
const descriptions: Record<string, string> = {
  "decay-coarse-step":
    "A decay simulation overshoots. Can a smaller step restore the physics?",
  "decay-wrong-sign":
    "The process succeeds, but concentration increases instead of decaying.",
  "decay-healthy":
    "Check a known-good experiment against the same independent specification.",
};
const outcomes: Record<string, string> = {
  QUEUED: "Waiting for execution",
  RUNNING: "Testing the experiment",
  VERIFIED_REPAIR: "Repair independently verified",
  VERIFIED_HEALTHY: "Healthy experiment verified",
  NOT_REPAIRED: "No verified repair",
  UNVERIFIED: "Verification unavailable",
  BLOCKED: "Experiment blocked",
  INCOMPLETE: "Experiment incomplete",
  CANCELLED: "Experiment cancelled",
  CONTAINED: "Probe contained",
  NOT_CONTAINED: "Containment not established",
};
const running = (v: ExperimentView) => ["QUEUED", "RUNNING"].includes(v.status);
const message = (e: unknown) =>
  e instanceof Error ? e.message : "The request could not be completed.";
function Plot({ run }: { run: ExperimentView }) {
  const attempts = run.report?.attempts ?? [];
  const [series, setSeries] = useState<
    { name: string; color: string; points: Point[] }[]
  >([]);
  const [error, setError] = useState("");
  const [time, setTime] = useState(2.5);
  const [hidden, setHidden] = useState<string[]>([]);
  useEffect(() => {
    const c = new AbortController();
    setSeries([]);
    setError("");
    const chosen =
      attempts.length > 1
        ? [attempts[0]!, attempts.at(-1)!]
        : attempts.slice(0, 1);
    void Promise.all(
      chosen.map(async (a, i) => {
        const file = a.jobs
          .find((j) => j.role === "primary")
          ?.artifacts.find((f) => f.label.endsWith("trajectory.csv"));
        if (!file)
          throw new Error(
            "Numeric evidence is unavailable. Inspect execution details and raw files.",
          );
        return {
          name: i ? "Candidate" : "Original",
          color: i ? "#087d76" : "#bd5e48",
          points: await trajectory(file, c.signal),
        };
      }),
    )
      .then((s) => {
        if (!c.signal.aborted) setSeries(s);
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(message(e));
      });
    return () => c.abort();
  }, [run.experiment_id, attempts.length, run.artifacts.length]);
  if (run.report?.evidence_expired || !attempts.length)
    return <p className="empty">Numeric evidence is unavailable.</p>;
  if (error)
    return (
      <p role="alert" className="notice">
        {error}
      </p>
    );
  if (!series.length)
    return <p role="status">Loading and checking numeric evidence…</p>;
  const p = attempts[0].parameters;
  const all = [
    ...series,
    {
      name: "Reference",
      color: "#718397",
      points: Array.from({ length: 201 }, (_, i) => ({
        t: i / 40,
        x: (p.x0 ?? 1) * Math.exp((-(p.k ?? 1) * i) / 40),
      })),
    },
  ];
  const values = all.flatMap((s) => s.points.map((p) => p.x));
  const lo = Math.min(0, ...values),
    hi = Math.max(1, ...values),
    span = hi - lo || 1;
  const x = (v: number) => 55 + (v / 5) * 690,
    y = (v: number) => 245 - ((v - lo) / span) * 210;
  return (
    <div className="plot">
      <div className="legend">
        {all.map((s) => (
          <label key={s.name} style={{ color: s.color }}>
            <input
              type="checkbox"
              checked={!hidden.includes(s.name)}
              onChange={() =>
                setHidden((h) =>
                  h.includes(s.name)
                    ? h.filter((n) => n !== s.name)
                    : [...h, s.name],
                )
              }
            />
            {s.name}
            {s.name === "Reference" ? " (analytical)" : ""}
          </label>
        ))}
      </div>
      <svg
        viewBox="0 0 780 290"
        role="img"
        aria-label="Original and final candidate concentration versus time with analytical reference"
      >
        {[0, 1, 2, 3, 4].map((i) => (
          <g key={i}>
            <line
              x1="55"
              x2="745"
              y1={y(lo + (span * i) / 4)}
              y2={y(lo + (span * i) / 4)}
              stroke="#e2e9ef"
            />
            <text x="46" y={y(lo + (span * i) / 4) + 4} textAnchor="end">
              {metric(lo + (span * i) / 4)}
            </text>
          </g>
        ))}
        {[0, 1, 2, 3, 4, 5].map((t) => (
          <text key={t} x={x(t)} y="265">
            {t}
          </text>
        ))}
        <text x="380" y="286">
          Time (s)
        </text>
        <text x="55" y="20">
          Concentration
        </text>
        {all
          .filter((s) => !hidden.includes(s.name))
          .map((s) => (
            <polyline
              key={s.name}
              fill="none"
              stroke={s.color}
              strokeWidth="2.5"
              strokeDasharray={s.name === "Reference" ? "5 5" : undefined}
              points={sampled(s.points)
                .map((p) => `${x(p.t)},${y(p.x)}`)
                .join(" ")}
            />
          ))}
        <line
          x1={x(time)}
          x2={x(time)}
          y1="35"
          y2="245"
          stroke="#8799ab"
          strokeDasharray="3 4"
        />
      </svg>
      <label className="scrubber">
        Inspect time: {time.toFixed(2)} s
        <input
          aria-label="Inspect time"
          type="range"
          min="0"
          max="5"
          step=".01"
          value={time}
          onChange={(e) => setTime(Number(e.target.value))}
        />
      </label>
      <div className="readout">
        {all
          .filter((s) => !hidden.includes(s.name))
          .map((s) => {
            const p = nearest(s.points, time);
            return (
              <span key={s.name}>
                {s.name}: <b>{metric(p?.x)}</b> at {metric(p?.t)} s
              </span>
            );
          })}
      </div>
      <p className="small muted">
        Measured samples; at most 801 points drawn per curve. Readout uses the
        nearest raw sample. The analytical overlay is a visual reference; the
        independent verifier determines the verdict.
      </p>
    </div>
  );
}
const tabs = ["Overview", "Patch", "Checks", "Evidence", "Provenance"] as const;
function Report({
  run,
  onError,
}: {
  run: ExperimentView;
  onError: (s: string) => void;
}) {
  const [tab, setTab] = useState<(typeof tabs)[number]>("Overview");
  const [busy, setBusy] = useState(false);
  const r = run.report!;
  const attempts = r.attempts ?? [];
  const expired = r.evidence_expired;
  const good =
    !expired &&
    ["VERIFIED_REPAIR", "VERIFIED_HEALTHY", "CONTAINED"].includes(run.status);
  async function save(fn: () => Promise<void>) {
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      onError(message(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="report" aria-label="Experiment report">
      <div className={`verdict ${good ? "verified" : ""}`}>
        <span className="eyebrow">INDEPENDENT RESULT</span>
        <h2>{expired ? "Evidence has expired" : outcomes[run.status]}</h2>
        <p>
          {r.error ??
            (good
              ? "The recorded result passed the trusted checks shown below."
              : "A successful process alone does not establish scientific validity.")}
        </p>
      </div>
      <div className="tabs" role="tablist" aria-label="Report sections">
        {tabs.map((t, i) => (
          <button
            key={t}
            role="tab"
            id={`tab-${t}`}
            aria-selected={t === tab}
            tabIndex={t === tab ? 0 : -1}
            aria-controls="report-panel"
            onClick={() => setTab(t)}
            onKeyDown={(e) => {
              if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) {
                e.preventDefault();
                const n =
                  e.key === "Home"
                    ? 0
                    : e.key === "End"
                      ? 4
                      : (i + (e.key === "ArrowRight" ? 1 : -1) + 5) % 5;
                setTab(tabs[n]);
                document.getElementById(`tab-${tabs[n]}`)?.focus();
              }
            }}
          >
            {t}
          </button>
        ))}
      </div>
      <div
        className="panel"
        role="tabpanel"
        id="report-panel"
        aria-labelledby={`tab-${tab}`}
      >
        {tab === "Overview" && (
          <>
            <div className="section-heading">
              <div>
                <span className="eyebrow">THE SCIENCE</span>
                <h3>Does the trajectory match the physics?</h3>
              </div>
              <span className="pill">
                {r.provenance?.mode ?? "No model mode recorded"}
              </span>
            </div>
            <p>
              {r.hypothesis ??
                "Inspect the independent measurements to understand this outcome."}
            </p>
            <Plot run={run} />
            {r.containment && (
              <>
                <h3>Containment observations</h3>
                {r.containment.connections.map((c, i) => (
                  <p key={i}>
                    {c.target}: {c.connected ? "connected" : "denied"} · errno{" "}
                    {c.errno ?? "unknown"}
                  </p>
                ))}
                <p>
                  Positive control: {String(r.containment.positive_control)} ·
                  messages received: {r.containment.messages_received} ·
                  cleanup: {r.containment.cleanup} · healthy afterward:{" "}
                  {String(r.containment.runner_healthy_after)}
                </p>
              </>
            )}
            <h3>Limits of this result</h3>
            <ul>
              {(r.limitations?.length
                ? r.limitations
                : [
                    "This result applies to the bounded decay fixture and recorded parameters.",
                  ]
              ).map((l, i) => (
                <li key={i}>{l}</li>
              ))}
            </ul>
          </>
        )}
        {tab === "Patch" && (
          <>
            <h3>What changed</h3>
            <p>{r.hypothesis ?? "No diagnosis was recorded."}</p>
            {r.patch ? (
              <pre className="diff" aria-label="Unified patch">
                {r.patch.split("\n").map((s, i) => (
                  <span
                    key={i}
                    className={
                      s.startsWith("+")
                        ? "added"
                        : s.startsWith("-")
                          ? "removed"
                          : ""
                    }
                  >
                    {s}
                    {"\n"}
                  </span>
                ))}
              </pre>
            ) : (
              <p className="empty">No patch was recorded.</p>
            )}
            {attempts.map((a) => (
              <details key={a.revision}>
                <summary>
                  {a.revision
                    ? `Candidate ${a.revision} source`
                    : "Original source"}
                </summary>
                <pre>{a.source}</pre>
              </details>
            ))}
          </>
        )}
        {tab === "Checks" &&
          (attempts.length ? (
            attempts.map((a) => (
              <section className="checks" key={a.revision}>
                <h3>
                  {a.revision ? `Candidate ${a.revision}` : "Original"}{" "}
                  <span className="pill">
                    {a.verification?.verdict ?? "UNVERIFIED"}
                  </span>
                </h3>
                <p>
                  dt = {metric(a.parameters.dt)} · k = {metric(a.parameters.k)}{" "}
                  · x₀ = {metric(a.parameters.x0)}
                </p>
                {a.verification ? (
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>Independent check</th>
                          <th>Result</th>
                          <th>Measured</th>
                          <th>Tolerance</th>
                        </tr>
                      </thead>
                      <tbody>
                        {a.verification.checks.map((c) => (
                          <tr key={c.key}>
                            <td>
                              {checkLabel(c.key)}
                              <small>
                                {c.key}
                                {c.detail ? ` · ${c.detail}` : ""}
                              </small>
                            </td>
                            <td className={c.passed ? "pass" : "fail"}>
                              {c.passed ? "Pass" : "Fail"}
                            </td>
                            <td>{metric(c.measured)}</td>
                            <td>{metric(c.tolerance)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="notice">No independent verdict was recorded.</p>
                )}
                <details>
                  <summary>Execution and cleanup</summary>
                  {a.jobs.map((j) => (
                    <p key={j.job_id}>
                      <b>{j.role}</b> · {j.execution.status} · exit{" "}
                      {j.execution.exit_code ?? "unknown"} ·{" "}
                      {j.execution.reason ?? "pending"} · cleanup{" "}
                      {j.execution.cleanup}
                    </p>
                  ))}
                </details>
              </section>
            ))
          ) : (
            <p className="empty">No independent checks are available.</p>
          ))}
        {tab === "Evidence" && (
          <>
            <div className="section-heading">
              <div>
                <h3>Take the evidence with you</h3>
                <p>
                  Sources, numerical results, logs, report and a SHA-256
                  manifest.
                </p>
              </div>
              <button
                className="primary"
                disabled={busy || expired || !run.artifacts.length}
                onClick={() =>
                  void save(() => downloadBundle(run.experiment_id))
                }
              >
                {busy ? "Preparing…" : "Download evidence ZIP"}
              </button>
            </div>
            {expired && (
              <p className="notice">
                The retention period ended. Original numeric evidence is no
                longer available.
              </p>
            )}
            <ul className="files">
              {run.artifacts.map((a) => (
                <li key={a.id}>
                  <div>
                    <strong>{a.label}</strong>
                    <small>
                      {bytes(a.size)} · SHA-256 {a.sha256}
                    </small>
                  </div>
                  <button
                    disabled={busy}
                    onClick={() => void save(() => downloadArtifact(a))}
                  >
                    Download
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
        {tab === "Provenance" && (
          <>
            <h3>Trace this result</h3>
            <p>
              Model output proposes a change. Independent verification
              establishes the scientific verdict.
            </p>
            <dl>
              <dt>Experiment</dt>
              <dd>{run.experiment_id}</dd>
              {Object.entries(r.provenance ?? {}).map(([k, v]) => (
                <div className="provenance-row" key={k}>
                  <dt>{k.replaceAll("_", " ")}</dt>
                  <dd>
                    {v == null
                      ? "Not recorded"
                      : typeof v === "object"
                        ? JSON.stringify(v)
                        : String(v)}
                  </dd>
                </div>
              ))}
            </dl>
          </>
        )}
      </div>
    </section>
  );
}
function App() {
  const [apps, setApps] = useState<AppView[]>([]),
    [selected, setSelected] = useState("decay-coarse-step"),
    [task, setTask] = useState(""),
    [ready, setReady] = useState(false),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [run, setRun] = useState<ExperimentView | null>(null),
    [events, setEvents] = useState<EventView[]>([]),
    [recent, setRecent] = useState<ExperimentSummary[]>([]),
    [poll, setPoll] = useState(0),
    [operator, setOperator] = useState("");
  const [previewMode, setPreviewMode] = useState("");
  const guard = useRef(false);
  const section = useRef<HTMLElement>(null);
  async function connect(force = false) {
    try {
      setError("");
      await api.bootstrap(force);
      const [a, r, info] = await Promise.all([
        api.apps(),
        api.recent(),
        api.info(),
      ]);
      setApps(a);
      setRecent(r);
      setPreviewMode(info.preview_mode ?? "");
      await api.health();
      setReady(true);
    } catch (e) {
      setReady(false);
      setError(message(e));
    }
  }
  async function open(id: string) {
    try {
      const v = await api.view(id);
      setRun(v);
      setEvents([]);
      setError("");
      history.replaceState(null, "", `?experiment=${id}`);
      setPoll((p) => p + 1);
    } catch (e) {
      setError(message(e));
    }
  }
  useEffect(() => {
    void connect();
    const id = new URLSearchParams(location.search).get("experiment");
    if (id && uuid.test(id))
      void api
        .bootstrap()
        .then(() => open(id))
        .catch((e) => setError(message(e)));
  }, []);
  useEffect(() => {
    if (!run) return;
    let stop = false,
      cursor = 0;
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const v = await api.view(run!.experiment_id);
        let batch: EventView[] = [];
        for (let p = 0; p < 20; p++) {
          const more = await api.events(v.experiment_id, cursor);
          if (stop) return;
          batch = batch.concat(more);
          if (more.length) cursor = more.at(-1)!.cursor;
          if (more.length < 100) break;
        }
        if (stop) return;
        setRun(v);
        setEvents((old) =>
          [...old, ...batch].filter(
            (e, i, a) => a.findIndex((x) => x.cursor === e.cursor) === i,
          ),
        );
        if (running(v)) timer = setTimeout(() => void refresh(), 1000);
        else
          void api
            .recent()
            .then(setRecent)
            .catch(() => {});
      } catch (e) {
        if (!stop) {
          setReady(false);
          setError(message(e));
        }
      }
    }
    void refresh();
    return () => {
      stop = true;
      clearTimeout(timer);
    };
  }, [run?.experiment_id, poll]);
  async function start(probe = false) {
    if (guard.current) return;
    guard.current = true;
    setBusy(true);
    setError("");
    try {
      const v = probe
        ? await api.probe(operator)
        : await api.start(selected, task);
      setOperator("");
      await open(v.experiment_id);
      setTimeout(
        () =>
          section.current?.scrollIntoView({
            behavior: "smooth",
            block: "start",
          }),
        50,
      );
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
      guard.current = false;
    }
  }
  async function cancel() {
    if (!run || guard.current) return;
    guard.current = true;
    setBusy(true);
    try {
      await api.cancel(run.experiment_id);
      setPoll((p) => p + 1);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
      guard.current = false;
    }
  }
  return (
    <>
      <header>
        <a className="brand" href="/" aria-label="Experiment Doctor home">
          <span className="brand-mark" />
          <span>
            Experiment <b>Doctor</b>
            <small>A SCIENTIFIC REPAIR WORKBENCH</small>
          </span>
        </a>
        <span className="connection">
          <i className={ready ? "online" : ""} />
          {ready ? "Experiment service ready" : "Service not connected"}
        </span>
      </header>
      <main>
        {previewMode && (
          <div className="preview-note" role="status">
            Offline preview · fixed model and numeric fixtures. No live
            inference or candidate execution. Mode: {previewMode}.
          </div>
        )}
        <section className="hero">
          <div>
            <span className="eyebrow">
              FROM A PLAUSIBLE RUN TO A PROVEN RESULT
            </span>
            <h1>
              Fix the experiment.
              <br />
              <em>Trust the evidence.</em>
            </h1>
            <p>
              Watch an AI diagnose a numerical experiment, propose a small
              repair, and put it through independent scientific checks.
            </p>
          </div>
          <aside className="equation">
            <span className="eyebrow">THE MODEL · EXPONENTIAL DECAY</span>
            <div>
              x(t) = x₀ e<sup>−kt</sup>
            </div>
            <p>
              Concentration should stay positive and decrease. A clean exit code
              cannot tell you that.
            </p>
            <small>ONE PHYSICAL LAW. THREE EXPERIMENTS.</small>
          </aside>
        </section>
        {error && (
          <div role="alert" className="notice">
            <strong>{error}</strong>
            <button
              onClick={() => {
                void connect(true);
                setPoll((p) => p + 1);
              }}
            >
              Reconnect
            </button>
          </div>
        )}
        <section className="intake">
          <div className="section-heading">
            <div>
              <span className="eyebrow">01 / CHOOSE AN EXPERIMENT</span>
              <h2>Start with a question.</h2>
            </div>
            <small className="muted">
              Fixed fixtures · isolated execution · independent checks
            </small>
          </div>
          <div className="cards">
            {["decay-coarse-step", "decay-wrong-sign", "decay-healthy"]
              .filter((id) => apps.some((a) => a.id === id))
              .map((id) => (
                <button
                  key={id}
                  className={`fixture ${selected === id ? "selected" : ""}`}
                  aria-pressed={selected === id}
                  onClick={() => setSelected(id)}
                >
                  <span className="eyebrow">
                    {id === "decay-healthy" ? "CONTROL" : "REPAIR CHALLENGE"}
                  </span>
                  <span className="radio" />
                  <svg viewBox="0 0 280 65" aria-hidden="true">
                    <path
                      d="M0 55 H280 M12 5 V55"
                      fill="none"
                      stroke="#d9e2eb"
                    />
                    <path
                      d={
                        id === "decay-coarse-step"
                          ? "M12 12 L75 60 L140 5 L205 65 L270 2"
                          : id === "decay-wrong-sign"
                            ? "M12 53 C120 53 200 40 270 5"
                            : "M12 8 C40 50 120 54 270 55"
                      }
                      fill="none"
                      stroke="#3975b4"
                      strokeWidth="2.5"
                    />
                  </svg>
                  <small className="illustration">Fixture illustration</small>
                  <h3>{titles[id]}</h3>
                  <p>{descriptions[id]}</p>
                </button>
              ))}
          </div>
          <div className="launch">
            <label>
              What should the doctor investigate?{" "}
              <span className="muted">(optional)</span>
              <textarea
                rows={2}
                maxLength={1000}
                value={task}
                onChange={(e) => setTask(e.target.value)}
                placeholder="Explain the issue or ask a question about this experiment."
              />
            </label>
            <div>
              <button
                className="primary"
                disabled={!ready || busy || !!(run && running(run))}
                onClick={() => void start()}
              >
                {busy ? "Submitting…" : "Diagnose experiment →"}
              </button>
              <p className="small muted">
                A run may take a few minutes. Reports belong to this browser
                session; evidence is retained for 24 hours.
              </p>
            </div>
          </div>
        </section>
        {run && (
          <section
            className="work"
            ref={section}
            tabIndex={-1}
            aria-label="Current experiment"
          >
            <div className="section-heading">
              <div>
                <span className="eyebrow">02 / FOLLOW THE EVIDENCE</span>
                <h2>
                  {titles[run.fixture_id] ?? "Controlled containment probe"}
                </h2>
              </div>
              {running(run) && (
                <button
                  disabled={busy || run.cancel_requested}
                  onClick={() => void cancel()}
                >
                  {run.cancel_requested
                    ? "Cancellation requested"
                    : "Cancel experiment"}
                </button>
              )}
            </div>
            <div className="work-grid">
              <aside className="timeline">
                <span className="pill">{outcomes[run.status]}</span>
                <ol aria-live="polite">
                  {events.map((e) => {
                    const label = eventLabel(e.kind, e.data);
                    return label ? (
                      <li key={e.cursor}>
                        <time>
                          {new Date(e.at * 1000).toLocaleTimeString()}
                        </time>
                        <span>{label}</span>
                      </li>
                    ) : null;
                  })}
                </ol>
                {running(run) && (
                  <p className="muted small" role="status">
                    Waiting for recorded progress…
                  </p>
                )}
              </aside>
              {run.report ? (
                <Report key={run.experiment_id} run={run} onError={setError} />
              ) : (
                <div className="waiting">
                  <div>✦</div>
                  <h3>{outcomes[run.status]}</h3>
                  <p>
                    {running(run)
                      ? "Execution and verification events will appear as work completes."
                      : "This run ended without a published evidence report."}
                  </p>
                  <p className="muted">
                    No scientific verdict has been recorded yet.
                  </p>
                </div>
              )}
            </div>
          </section>
        )}
        {!!recent.length && (
          <section className="recent">
            <h3>Your recent experiments</h3>
            {recent.map((r) => (
              <button
                key={r.experiment_id}
                onClick={() => void open(r.experiment_id)}
              >
                <span>{titles[r.fixture_id] ?? "Containment probe"}</span>
                <small>
                  {outcomes[r.status]} ·{" "}
                  {new Date(r.created_at * 1000).toLocaleString()}
                </small>
                <span>↗</span>
              </button>
            ))}
          </section>
        )}
        <details className="operator">
          <summary>Operator controls</summary>
          <p>
            The fixed network probe requires a separate operator credential and
            server enablement. It is disabled by default.
          </p>
          <label>
            Operator credential
            <input
              type="password"
              autoComplete="off"
              value={operator}
              onChange={(e) => setOperator(e.target.value)}
            />
          </label>
          <button
            disabled={!ready || busy || !operator || !!(run && running(run))}
            onClick={() => void start(true)}
          >
            Run controlled containment probe
          </button>
        </details>
      </main>
      <footer>
        <strong>Experiment Doctor</strong>
        <span>Propose with a model. Verify with measurements.</span>
        <span>Decay specification v1</span>
      </footer>
    </>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
