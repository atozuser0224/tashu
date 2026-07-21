import type {
  Coordinate,
  CoreScenario,
  DriverLivePosition,
  MissionDetail,
  MissionListResponse,
  MissionStatus,
  MissionSummary,
  OperationsBootstrap,
  PlanResponse,
  QrChallenge,
  RewardTransaction,
  RewardTransactionListResponse,
  StationQr,
  Wallet,
} from "../types/api";

export interface ApiClientOptions {
  baseUrl: string;
  driverId?: string;
  deviceId?: string;
  fetchImpl?: typeof fetch;
}

export interface ReportLocationOptions {
  accuracyMeters?: number;
  speedKmh?: number | null;
}

export interface VerifyStationQrInput {
  location: Coordinate;
  qrPayload: string;
  challengeId: string;
  integrityProvider?: "development" | "play_integrity" | "app_attest";
  integrityToken?: string | null;
}

export interface CompleteStopInput {
  location: Coordinate;
  actualQuantity: number;
  bikeQrCodes?: string[];
  evidencePhotoUrl?: string | null;
}

interface RequestOptions {
  method?: "GET" | "POST";
  role: "admin" | "driver";
  body?: unknown;
  headers?: Record<string, string>;
}

export class ApiError extends Error {
  readonly status: number;
  readonly url: string;
  readonly detail: string;
  readonly payload: unknown;

  constructor(status: number, url: string, detail: string, payload: unknown) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.url = url;
    this.detail = detail;
    this.payload = payload;
    Object.setPrototypeOf(this, ApiError.prototype);
  }
}

export class ApiClient {
  readonly baseUrl: string;
  readonly driverId: string;
  readonly deviceId: string;

  private readonly fetchImpl: typeof fetch;

  constructor({
    baseUrl,
    driverId = "DRIVER-01",
    deviceId = "ridego-test-device",
    fetchImpl = fetch,
  }: ApiClientOptions) {
    const normalizedBaseUrl = baseUrl.trim().replace(/\/+$/, "");
    if (!normalizedBaseUrl) {
      throw new Error("API baseUrl is required.");
    }
    if (!driverId.trim()) {
      throw new Error("driverId is required.");
    }
    if (!deviceId.trim()) {
      throw new Error("deviceId is required.");
    }

    this.baseUrl = normalizedBaseUrl;
    this.driverId = driverId.trim();
    this.deviceId = deviceId.trim();
    // Window.fetch throws "Illegal invocation" when detached from Window on web.
    // Binding to globalThis is also valid in React Native and keeps injected mocks usable.
    this.fetchImpl = fetchImpl.bind(globalThis);
  }

  sampleCore(): Promise<CoreScenario> {
    return this.request<CoreScenario>("/api/v1/test/core-scenarios/sample", {
      role: "admin",
    });
  }

  resetTestData(): Promise<{ reset: boolean }> {
    return this.request<{ reset: boolean }>("/api/v1/test/reset", {
      method: "POST",
      role: "admin",
    });
  }

  createCorePlan(scenario: CoreScenario, tmapKey?: string): Promise<PlanResponse> {
    const transientKey = tmapKey?.trim();
    return this.request<PlanResponse>("/api/v1/test/core-scenarios/plan", {
      method: "POST",
      role: "admin",
      body: scenario,
      headers: transientKey ? { "X-Test-Tmap-Key": transientKey } : undefined,
    });
  }

  bootstrap(): Promise<OperationsBootstrap> {
    return this.request<OperationsBootstrap>(
      `/api/v1/operations/bootstrap?driver_id=${encodeURIComponent(this.driverId)}`,
      { role: "driver" },
    );
  }

  async listMissions(status?: MissionStatus): Promise<MissionSummary[]> {
    const query = new URLSearchParams({ driver_id: this.driverId });
    if (status) {
      query.set("status", status);
    }
    const response = await this.request<MissionListResponse>(
      `/api/v1/operations/missions?${query.toString()}`,
      { role: "driver" },
    );
    return response.missions;
  }

  getMission(missionId: string): Promise<MissionDetail> {
    return this.request<MissionDetail>(
      `/api/v1/operations/missions/${encodeURIComponent(missionId)}`,
      { role: "driver" },
    );
  }

  acceptMission(missionId: string): Promise<MissionDetail> {
    return this.driverAction(missionId, "accept");
  }

  startMission(missionId: string): Promise<MissionDetail> {
    return this.driverAction(missionId, "start");
  }

  accept(missionId: string): Promise<MissionDetail> {
    return this.acceptMission(missionId);
  }

  start(missionId: string): Promise<MissionDetail> {
    return this.startMission(missionId);
  }

  reportLocation(
    location: Coordinate,
    options: ReportLocationOptions = {},
  ): Promise<DriverLivePosition> {
    return this.request<DriverLivePosition>("/api/v1/operations/drivers/me/location", {
      method: "POST",
      role: "driver",
      body: {
        location,
        recorded_at: new Date().toISOString(),
        accuracy_meters: options.accuracyMeters ?? 5,
        speed_kmh: options.speedKmh ?? null,
        device_id: this.deviceId,
      },
    });
  }

  createStationQr(stationId: string): Promise<StationQr> {
    return this.request<StationQr>(
      `/api/v1/test/stations/${encodeURIComponent(stationId)}/qr`,
      { method: "POST", role: "admin" },
    );
  }

  createQrChallenge(
    missionId: string,
    sequence: number,
  ): Promise<QrChallenge> {
    return this.request<QrChallenge>(this.stopPath(missionId, sequence, "qr-challenge"), {
      method: "POST",
      role: "driver",
      body: this.driverBody({
        device_id: this.deviceId,
      }),
    });
  }

  verifyStationQr(
    missionId: string,
    sequence: number,
    input: VerifyStationQrInput,
  ): Promise<MissionDetail> {
    return this.request<MissionDetail>(this.stopPath(missionId, sequence, "verify-qr"), {
      method: "POST",
      role: "driver",
      body: this.driverBody({
        location: input.location,
        qr_payload: input.qrPayload,
        challenge_id: input.challengeId,
        device_id: this.deviceId,
        integrity_provider: input.integrityProvider ?? "development",
        integrity_token: input.integrityToken ?? null,
      }),
    });
  }

  completeStop(
    missionId: string,
    sequence: number,
    input: CompleteStopInput,
  ): Promise<MissionDetail> {
    return this.request<MissionDetail>(this.stopPath(missionId, sequence, "complete"), {
      method: "POST",
      role: "driver",
      body: this.driverBody({
        location: input.location,
        actual_quantity: input.actualQuantity,
        bike_qr_codes: input.bikeQrCodes ?? [],
        evidence_photo_url: input.evidencePhotoUrl ?? null,
      }),
    });
  }

  getWallet(): Promise<Wallet> {
    return this.request<Wallet>(
      `/api/v1/rewards/wallets/${encodeURIComponent(this.driverId)}`,
      { role: "driver" },
    );
  }

  async getTransactions(): Promise<RewardTransaction[]> {
    const response = await this.request<RewardTransactionListResponse>(
      `/api/v1/rewards/wallets/${encodeURIComponent(this.driverId)}/transactions`,
      { role: "driver" },
    );
    return response.transactions;
  }

  private driverAction(
    missionId: string,
    action: "accept" | "start",
  ): Promise<MissionDetail> {
    return this.request<MissionDetail>(
      `/api/v1/operations/missions/${encodeURIComponent(missionId)}/${action}`,
      {
        method: "POST",
        role: "driver",
        body: this.driverBody(),
      },
    );
  }

  private driverBody<T extends Record<string, unknown>>(extra?: T): T & { driver_id: string } {
    return { ...(extra ?? ({} as T)), driver_id: this.driverId };
  }

  private stopPath(missionId: string, sequence: number, action: string): string {
    if (!Number.isInteger(sequence) || sequence < 1) {
      throw new Error("Stop sequence must be a positive integer.");
    }
    return `/api/v1/operations/missions/${encodeURIComponent(
      missionId,
    )}/stops/${sequence}/${action}`;
  }

  private async request<T>(path: string, options: RequestOptions): Promise<T> {
    const url = `${this.baseUrl}${path.startsWith("/") ? path : `/${path}`}`;
    const headers: Record<string, string> = {
      Accept: "application/json",
      ...(options.body === undefined ? {} : { "Content-Type": "application/json" }),
      ...(options.role === "admin"
        ? { "X-Test-Role": "admin" }
        : {
            "X-Test-Role": "driver",
            "X-Test-Driver-Id": this.driverId,
          }),
      ...options.headers,
    };

    let response: Response;
    try {
      response = await this.fetchImpl(url, {
        method: options.method ?? "GET",
        headers,
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown network error";
      throw new ApiError(0, url, `서버에 연결할 수 없습니다: ${message}`, error);
    }

    const text = await response.text();
    const payload = parseResponseBody(text);
    if (!response.ok) {
      throw new ApiError(response.status, url, errorDetail(payload, response.status), payload);
    }
    if (response.status === 204 || text.length === 0) {
      return undefined as T;
    }
    if (typeof payload === "string") {
      throw new ApiError(
        response.status,
        url,
        "서버가 JSON이 아닌 응답을 반환했습니다.",
        payload,
      );
    }
    return payload as T;
  }
}

export function createApiClient(options: ApiClientOptions): ApiClient {
  return new ApiClient(options);
}

function parseResponseBody(text: string): unknown {
  if (!text) {
    return undefined;
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

function errorDetail(payload: unknown, status: number): string {
  if (isRecord(payload) && "detail" in payload) {
    const detail = payload.detail;
    if (typeof detail === "string") {
      return detail;
    }
    try {
      return JSON.stringify(detail);
    } catch {
      return String(detail);
    }
  }
  if (typeof payload === "string" && payload.trim()) {
    return payload;
  }
  return `API 요청에 실패했습니다. (HTTP ${status})`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
