// frontend/src/types.ts

export interface User {
  id: string;
  username: string;
  role: string;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface RefreshResponse {
  access_token: string;
  token_type: string;
}

export interface AffectedFile {
  file: string;
  change_type: 'create' | 'modify' | 'delete';
  description: string;
}

export interface Complexity {
  score: number;
  label: 'low' | 'medium' | 'high';
  estimated_effort: string;
  reasoning: string;
}

export interface ResearchMetrics {
  files_affected: number;
  files_created: number;
  files_modified: number;
  services_affected: number;
  contract_changes: boolean;
  new_dependencies: string[];
  risk_areas: string[];
}

export interface ResearchOutput {
  summary: string;
  affected_code: AffectedFile[];
  complexity: Complexity;
  metrics: ResearchMetrics;
}

export interface TaskLog {
  id: number;
  event: string;
  actor_id: string | null;
  detail: Record<string, unknown> | null;
  created_at: string;
}

export interface TaskListItem {
  id: string;
  feature_name: string;
  repo: string;
  state: string;
  submitter_id: string;
  submitter_username: string;
  created_at: string;
}

export interface TaskOut {
  id: string;
  feature_name: string;
  description: string;
  repo: string;
  branch_from: string;
  state: string;
  submitter_id: string;
  approved_by_id: string | null;
  approved_at: string | null;
  additional_context: string[];
  optional_answers: Record<string, unknown>;
  research: ResearchOutput | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  logs: TaskLog[];
}

export interface RepoInfo {
  name: string;
  path: string;
  tc_indexed: boolean;
  tc_node_count: number | null;
  tc_last_indexed: string | null;
}

export interface TaskCreate {
  feature_name: string;
  description: string;
  repo: string;
  branch_from: string;
  additional_context: string[];
  optional_answers: Record<string, unknown>;
}
