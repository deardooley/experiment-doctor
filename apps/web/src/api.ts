import type {
  AppView,
  ArtifactView,
  EventView,
  ExperimentSummary,
  ExperimentView,
  SessionView,
} from "./generated/contracts";
import { parseTrajectory, uuid } from "./data";
import { digestHex } from "./hash";

export class APIError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}
const messages: Record<number, string> = {
  401: "Your browser session expired. Reconnect before continuing.",
  403: "The session or operator permission check failed. Refresh your session or check the operator credential.",
  404: "This experiment or evidence is not available in your browser session.",
  409: "Evidence is not ready yet.",
  410: "This evidence has expired.",
  429: "The queue or usage limit has been reached. Try again later.",
  503: "The experiment service is unavailable. No result has been inferred.",
};

async function response(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  try {
    const result = await fetch(path, {
      ...init,
      credentials: "same-origin",
      cache: "no-store",
    });
    if (!result.ok)
      throw new APIError(
        result.status,
        messages[result.status] ?? "The request could not be completed.",
      );
    return result;
  } catch (error) {
    if (
      error instanceof APIError ||
      (error instanceof Error && error.name === "AbortError")
    )
      throw error;
    throw new APIError(
      0,
      "Connection lost. Reconnect to check existing work before starting another run.",
    );
  }
}
async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const result = await response(path, init);
  try {
    return (await result.json()) as T;
  } catch {
    throw new APIError(502, "The service returned an unreadable response.");
  }
}
function id(value: string): string {
  if (!uuid.test(value)) throw new Error("Invalid evidence identity.");
  return value;
}

class Client {
  csrf: string | null = null;
  bootstrapRequest: Promise<SessionView> | null = null;
  bootstrap(force = false): Promise<SessionView> {
    if (!this.bootstrapRequest || force) {
      this.bootstrapRequest = json<SessionView>("/api/v1/session")
        .then((session) => {
          this.csrf = session.csrf_token;
          return session;
        })
        .catch((error) => {
          this.bootstrapRequest = null;
          throw error;
        });
    }
    return this.bootstrapRequest;
  }
  async mutation<T>(
    path: string,
    body?: unknown,
    operatorToken?: string,
  ): Promise<T> {
    if (!this.csrf) throw new APIError(401, messages[401]);
    const headers: Record<string, string> = {
      "X-CSRF-Token": this.csrf,
      "Content-Type": "application/json",
    };
    if (operatorToken) headers.Authorization = `Bearer ${operatorToken}`;
    return json<T>(path, {
      method: "POST",
      headers,
      body: JSON.stringify(body ?? {}),
    });
  }
  apps = () => json<AppView[]>("/api/v1/apps");
  recent = () => json<ExperimentSummary[]>("/api/v1/experiments");
  health = () => json<{ status: string }>("/health/ready");
  info = () =>
    json<{ status: string; release_id?: string | null; preview_mode?: string }>(
      "/health/live",
    );
  view = (experiment: string) =>
    json<ExperimentView>(`/api/v1/experiments/${id(experiment)}/view`);
  events = (experiment: string, after: number) =>
    json<EventView[]>(
      `/api/v1/experiments/${id(experiment)}/events?after=${after}`,
    );
  start = (fixture: string, task: string) =>
    this.mutation<{ experiment_id: string }>("/api/v1/experiments", {
      fixture_id: fixture,
      ...(task.trim() ? { task: task.trim() } : {}),
    });
  cancel = (experiment: string) =>
    this.mutation(`/api/v1/experiments/${id(experiment)}/cancel`);
  probe = (token: string) =>
    this.mutation<{ experiment_id: string }>(
      "/api/v1/operator/probes/network",
      {},
      token,
    );
}
export const api = new Client();

async function binary(
  path: string,
  maximum: number,
  signal?: AbortSignal,
): Promise<Uint8Array> {
  const result = await response(path, { signal });
  const reader = result.body?.getReader();
  if (!reader) throw new Error("Evidence stream is unavailable.");
  const chunks: Uint8Array[] = [];
  let length = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      length += value.length;
      if (length > maximum)
        throw new Error("Evidence exceeds the bounded download limit.");
      chunks.push(value);
    }
  } catch (error) {
    await reader.cancel();
    throw error;
  } finally {
    reader.releaseLock();
  }
  const data = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    data.set(chunk, offset);
    offset += chunk.length;
  }
  return data;
}
async function artifactBytes(
  artifact: ArtifactView,
  maximum: number,
  signal?: AbortSignal,
): Promise<Uint8Array> {
  if (artifact.size > maximum)
    throw new Error(
      "Trajectory exceeds the bounded plot limit. Download its raw file instead.",
    );
  const data = await binary(
    `/api/v1/artifacts/${id(artifact.id)}`,
    maximum,
    signal,
  );
  const hash = digestHex(data);
  if (data.length !== artifact.size || hash !== artifact.sha256)
    throw new Error("Evidence integrity check failed.");
  return data;
}
export async function trajectory(artifact: ArtifactView, signal: AbortSignal) {
  return parseTrajectory(
    new TextDecoder("utf-8", { fatal: true }).decode(
      await artifactBytes(artifact, 524288, signal),
    ),
  );
}
function save(data: Uint8Array, filename: string, type: string) {
  const url = URL.createObjectURL(new Blob([data as BlobPart], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export async function downloadArtifact(artifact: ArtifactView) {
  save(
    await artifactBytes(artifact, 10 * 1024 * 1024),
    artifact.name,
    "application/octet-stream",
  );
}
export async function downloadBundle(experiment: string) {
  save(
    await binary(
      `/api/v1/experiments/${id(experiment)}/evidence`,
      33 * 1024 * 1024,
    ),
    `experiment-${experiment}-evidence.zip`,
    "application/zip",
  );
}
