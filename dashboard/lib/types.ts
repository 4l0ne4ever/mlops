export type VersionStatus =
  | "active"
  | "promoted"
  | "rolled_back"
  | "failed"
  | "pending"
  | "completed"
  | "unknown";

export type HealthStatus =
  | "healthy"
  | "unhealthy"
  | "timeout"
  | "unreachable"
  | "error";

export interface VersionRecord {
  version_id: string;
  version_label: string;
  created_at: string;
  status: VersionStatus | string;
}

export interface EvalDetailRecord {
  test_case_id: string;
  input: string;
  expected_output: string;
  actual_output: string;
  score: number;
  accuracy: number;
  fluency: number;
  completeness: number;
  reasoning: string;
  issues: string[];
  passed: boolean;
  skipped: boolean;
  latency_ms: number;
  estimated_cost_usd: number;
  status: string;
}

export interface EvalResultRecord {
  result_id: string;
  run_id: string;
  version_id: string;
  quality_score: number | string | Record<string, unknown>;
  score_breakdown: Record<string, unknown> | string;
  total_test_cases: number;
  passed_test_cases: number;
  status: string;
  timestamp: string;
  details: EvalDetailRecord[];
  errors?: string[];
}

export interface DecisionLogEntry {
  timestamp: string;
  level: string;
  message: string;
  decision_id?: string;
  run_id?: string;
  decision?: string;
  reasoning?: string;
  v_new_id?: string;
  v_current_id?: string;
  action_taken?: string;
  comparison_report?: ComparisonReport;
}

export interface DeploymentStatus {
  current_version_id: string;
  status: string;
  deployed_at?: string;
  deployment_id?: string;
  previous_version_id?: string;
  environment?: string;
}

export interface HealthCheckResult {
  status: HealthStatus | string;
  status_code?: number;
  response_time_ms: number;
  timestamp: string;
  error?: string;
}

export interface ComparisonDelta {
  dimension: string;
  old: number;
  new: number;
  delta: number;
}

export interface ComparisonReport {
  verdict: string;
  v_new_score: number;
  v_current_score: number;
  delta: number;
  regressions: ComparisonDelta[];
  improvements: ComparisonDelta[];
  v_new_id?: string;
  v_current_id?: string;
  thresholds_used?: Record<string, number>;
}

export interface EnrichedVersionRecord extends VersionRecord {
  latest_quality_score: number;
  latest_run_id: string;
  latest_run_timestamp: string;
  total_test_cases: number;
  passed_test_cases: number;
}

export interface EnrichedRunRecord {
  result_id: string;
  run_id: string;
  version_id: string;
  quality_score: number;
  score_breakdown: Record<string, number>;
  total_test_cases: number;
  passed_test_cases: number;
  status: string;
  timestamp: string;
  decision: string;
  reasoning: string;
  action_taken: string;
  comparison_report?: ComparisonReport;
  details: EvalDetailRecord[];
}

export interface OverviewData {
  currentVersion: EnrichedVersionRecord | null;
  stagingVersion: string;
  productionDeployment: DeploymentStatus;
  stagingDeployment: DeploymentStatus;
  productionHealth: HealthCheckResult | null;
  stagingHealth: HealthCheckResult | null;
  recentRuns: EnrichedRunRecord[];
  latestDecision: DecisionLogEntry | null;
  totalVersions: number;
  promotedVersions: number;
  pendingVersions: number;
}

export interface DriftPoint {
  timestamp: string;
  version_id: string;
  quality_score: number;
  task_completion: number;
  output_quality: number;
  latency: number;
  cost_efficiency: number;
}

export interface DriftData {
  points: DriftPoint[];
}

export interface ComparisonRow {
  test_case_id: string;
  input: string;
  expected_output: string;
  left_output: string;
  right_output: string;
  left_score: number;
  right_score: number;
  delta: number;
  left_status: string;
  right_status: string;
}

export interface ComparisonViewData {
  leftVersion: EnrichedVersionRecord | null;
  rightVersion: EnrichedVersionRecord | null;
  leftRun: EnrichedRunRecord | null;
  rightRun: EnrichedRunRecord | null;
  rows: ComparisonRow[];
  selectedLeft: string;
  selectedRight: string;
  versions: EnrichedVersionRecord[];
}

export interface RuntimeAppConfig {
  environment: string;
  productionUrl: string;
  stagingUrl: string;
}