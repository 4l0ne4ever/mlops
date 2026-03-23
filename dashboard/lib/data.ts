import "server-only";

import {
  ComparisonRow,
  ComparisonViewData,
  DecisionLogEntry,
  DeploymentStatus,
  DriftData,
  DriftPoint,
  EnrichedRunRecord,
  EnrichedVersionRecord,
  EvalDetailRecord,
  EvalResultRecord,
  HealthCheckResult,
  OverviewData,
  VersionRecord,
} from "@/lib/types";
import { callMcpTool } from "@/lib/mcp";
import { getRuntimeAppConfig } from "@/lib/runtime-config";

const DIMENSION_KEYS = [
  "task_completion",
  "output_quality",
  "latency",
  "cost_efficiency",
] as const;

function coerceNumber(value: unknown): number {
  if (typeof value === "number") {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return coerceNumber(record.score ?? record.value ?? 0);
  }
  return 0;
}

function coerceBreakdown(value: unknown): Record<string, number> {
  const parsed =
    typeof value === "string"
      ? (() => {
          try {
            return JSON.parse(value) as Record<string, unknown>;
          } catch {
            return {};
          }
        })()
      : value && typeof value === "object"
        ? (value as Record<string, unknown>)
        : {};

  return DIMENSION_KEYS.reduce<Record<string, number>>((acc, key) => {
    acc[key] = coerceNumber(parsed[key]);
    return acc;
  }, {});
}

function normalizeEvalResult(record: EvalResultRecord): EnrichedRunRecord {
  return {
    result_id: record.result_id,
    run_id: record.run_id,
    version_id: record.version_id,
    quality_score: coerceNumber(record.quality_score),
    score_breakdown: coerceBreakdown(record.score_breakdown),
    total_test_cases: record.total_test_cases ?? 0,
    passed_test_cases: record.passed_test_cases ?? 0,
    status: record.status ?? "unknown",
    timestamp: record.timestamp,
    decision: "PENDING",
    reasoning: "",
    action_taken: "",
    comparison_report: undefined,
    details: (record.details ?? []) as EvalDetailRecord[],
  };
}

function decisionByRun(logs: DecisionLogEntry[]): Map<string, DecisionLogEntry> {
  return new Map(logs.filter((entry) => entry.run_id).map((entry) => [entry.run_id as string, entry]));
}

function enrichRuns(evalResults: EvalResultRecord[], decisions: DecisionLogEntry[]): EnrichedRunRecord[] {
  const decisionMap = decisionByRun(decisions);

  return evalResults
    .map((record) => {
      const normalized = normalizeEvalResult(record);
      const decision = decisionMap.get(record.run_id);
      if (!decision) {
        return normalized;
      }
      return {
        ...normalized,
        decision: decision.decision ?? "PENDING",
        reasoning: decision.reasoning ?? "",
        action_taken: decision.action_taken ?? "",
        comparison_report: decision.comparison_report,
      };
    })
    .sort((left, right) => right.timestamp.localeCompare(left.timestamp));
}

function enrichVersions(versions: VersionRecord[], runs: EnrichedRunRecord[]): EnrichedVersionRecord[] {
  const latestByVersion = new Map<string, EnrichedRunRecord>();

  for (const run of runs) {
    if (!latestByVersion.has(run.version_id)) {
      latestByVersion.set(run.version_id, run);
    }
  }

  return versions.map((version) => {
    const latest = latestByVersion.get(version.version_id);
    return {
      ...version,
      latest_quality_score: latest?.quality_score ?? 0,
      latest_run_id: latest?.run_id ?? "",
      latest_run_timestamp: latest?.timestamp ?? "",
      total_test_cases: latest?.total_test_cases ?? 0,
      passed_test_cases: latest?.passed_test_cases ?? 0,
    };
  });
}

async function listVersions(limit = 100): Promise<VersionRecord[]> {
  return callMcpTool<VersionRecord[]>("storage", "list_versions", {
    limit,
    status_filter: "all",
  });
}

async function getEvalResults(versionId = "", runId = ""): Promise<EvalResultRecord[]> {
  return callMcpTool<EvalResultRecord[]>("storage", "get_eval_results", {
    version_id: versionId,
    run_id: runId,
  });
}

async function getDeploymentStatus(environment: "production" | "staging"): Promise<DeploymentStatus> {
  return callMcpTool<DeploymentStatus>("deploy", "get_deployment_status", {
    deployment_id: "",
    environment,
  });
}

async function getDecisionLogs(timeRange = "last_30d"): Promise<DecisionLogEntry[]> {
  return callMcpTool<DecisionLogEntry[]>("monitor", "get_logs", {
    log_group: "decisions",
    filter_pattern: "Decision:",
    time_range: timeRange,
  });
}

async function getHealth(endpointUrl: string): Promise<HealthCheckResult> {
  return callMcpTool<HealthCheckResult>("monitor", "check_health", {
    endpoint_url: `${endpointUrl.replace(/\/$/, "")}/health`,
  });
}

export async function getOverviewData(): Promise<OverviewData> {
  const runtime = await getRuntimeAppConfig();
  const [versions, evalResults, decisions, productionDeployment, stagingDeployment, productionHealth, stagingHealth] = await Promise.all([
    listVersions(100),
    getEvalResults(),
    getDecisionLogs("last_30d"),
    getDeploymentStatus("production"),
    getDeploymentStatus("staging"),
    getHealth(runtime.productionUrl),
    getHealth(runtime.stagingUrl),
  ]);

  const runs = enrichRuns(evalResults, decisions);
  const enrichedVersions = enrichVersions(versions, runs);
  const currentVersion = enrichedVersions.find(
    (version) => version.version_id === productionDeployment.current_version_id,
  ) ?? null;

  return {
    currentVersion,
    stagingVersion: stagingDeployment.current_version_id ?? "",
    productionDeployment,
    stagingDeployment,
    productionHealth,
    stagingHealth,
    recentRuns: runs.slice(0, 6),
    latestDecision: decisions[0] ?? null,
    totalVersions: enrichedVersions.length,
    promotedVersions: enrichedVersions.filter((version) => version.status === "promoted").length,
    pendingVersions: enrichedVersions.filter((version) => version.status === "pending").length,
  };
}

export async function getVersionsData(): Promise<EnrichedVersionRecord[]> {
  const [versions, evalResults, decisions] = await Promise.all([
    listVersions(100),
    getEvalResults(),
    getDecisionLogs("last_30d"),
  ]);

  return enrichVersions(versions, enrichRuns(evalResults, decisions)).sort(
    (left, right) => right.created_at.localeCompare(left.created_at),
  );
}

export async function getDriftData(): Promise<DriftData> {
  const evalResults = await getEvalResults();

  const points: DriftPoint[] = evalResults
    .map((record) => {
      const breakdown = coerceBreakdown(record.score_breakdown);
      return {
        timestamp: record.timestamp,
        version_id: record.version_id,
        quality_score: coerceNumber(record.quality_score),
        task_completion: breakdown.task_completion ?? 0,
        output_quality: breakdown.output_quality ?? 0,
        latency: breakdown.latency ?? 0,
        cost_efficiency: breakdown.cost_efficiency ?? 0,
      };
    })
    .sort((left, right) => left.timestamp.localeCompare(right.timestamp));

  return { points };
}

export async function getRunsData(): Promise<EnrichedRunRecord[]> {
  const [evalResults, decisions] = await Promise.all([
    getEvalResults(),
    getDecisionLogs("last_30d"),
  ]);

  return enrichRuns(evalResults, decisions);
}

export async function getRunDetail(runId: string): Promise<EnrichedRunRecord | null> {
  const [results, decisions] = await Promise.all([
    getEvalResults("", runId),
    getDecisionLogs("last_30d"),
  ]);

  const runs = enrichRuns(results, decisions);
  return runs.find((run) => run.run_id === runId) ?? null;
}

export async function getComparisonData(
  leftVersionId?: string,
  rightVersionId?: string,
): Promise<ComparisonViewData> {
  const [versions, runs] = await Promise.all([getVersionsData(), getRunsData()]);

  const fallbackLeft = leftVersionId ?? versions[0]?.version_id ?? "";
  const fallbackRight =
    rightVersionId ??
    versions.find((version) => version.version_id !== fallbackLeft)?.version_id ??
    "";

  const leftRun = runs.find((run) => run.version_id === fallbackLeft) ?? null;
  const rightRun = runs.find((run) => run.version_id === fallbackRight) ?? null;
  const leftVersion = versions.find((version) => version.version_id === fallbackLeft) ?? null;
  const rightVersion = versions.find((version) => version.version_id === fallbackRight) ?? null;

  const rightDetails = new Map((rightRun?.details ?? []).map((detail) => [detail.test_case_id, detail]));
  const leftRows = (leftRun?.details ?? []).map<ComparisonRow>((detail) => {
    const match = rightDetails.get(detail.test_case_id);
    return {
      test_case_id: detail.test_case_id,
      input: detail.input,
      expected_output: detail.expected_output,
      left_output: detail.actual_output,
      right_output: match?.actual_output ?? "",
      left_score: coerceNumber(detail.score),
      right_score: coerceNumber(match?.score),
      delta: coerceNumber(detail.score) - coerceNumber(match?.score),
      left_status: detail.status,
      right_status: match?.status ?? "missing",
    };
  });

  const missingOnLeft = (rightRun?.details ?? [])
    .filter((detail) => !(leftRun?.details ?? []).some((left) => left.test_case_id === detail.test_case_id))
    .map<ComparisonRow>((detail) => ({
      test_case_id: detail.test_case_id,
      input: detail.input,
      expected_output: detail.expected_output,
      left_output: "",
      right_output: detail.actual_output,
      left_score: 0,
      right_score: coerceNumber(detail.score),
      delta: -coerceNumber(detail.score),
      left_status: "missing",
      right_status: detail.status,
    }));

  return {
    leftVersion,
    rightVersion,
    leftRun,
    rightRun,
    rows: [...leftRows, ...missingOnLeft],
    selectedLeft: fallbackLeft,
    selectedRight: fallbackRight,
    versions,
  };
}