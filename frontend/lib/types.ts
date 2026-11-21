export type Role = "admin" | "operator" | "viewer";

export interface User { id: string; email: string; name: string; role: Role; is_active: boolean; created_at: string }

export type SiteStatus = "draft" | "generating" | "preview" | "awaiting_approval" | "live" | "failed" | "archived";
export type Health = "up" | "down" | "degraded" | "unknown";

export interface Palette { primary: string; secondary: string; accent: string; background: string; surface: string; text: string; muted: string }

export interface Website {
  id: string; name: string; slug: string; prompt: string; stack: string; stack_selected_by: "user" | "ai";
  status: SiteStatus; domain: string | null; hosting_provider: string; dns_provider: string;
  hosting_account_id: string | null; dns_account_id: string | null; require_approval: boolean;
  live_url: string | null; health_status: Health; last_checked_at: string | null; current_deployment_id: string | null;
  created_at: string; updated_at: string; palette: Palette | null; tagline: string | null; quality_score: number | null; topic: string | null;
  domain_mode?: "buy" | "existing" | null;
  config?: Record<string, any>; env?: Record<string, string>;
}

export type StepStatus = "pending" | "running" | "completed" | "failed" | "waiting" | "retrying" | "skipped";

export interface LogLine { ts: string; level: "info" | "success" | "warning" | "error"; message: string }

export interface Highlight {
  type: "kv" | "chips" | "palette" | "images" | "checks" | "fonts" | "link";
  label?: string; items?: any[]; url?: string;
}

export interface JobStep {
  id: string; key: string; name: string; agent: string; order: number; status: StepStatus; progress: number;
  logs: LogLine[]; output: { summary?: string; highlights?: Highlight[]; error?: PipelineErr }; error: string | null;
  attempts: number; started_at: string | null; finished_at: string | null;
}

export interface PipelineErr { message: string; code: string; hint?: string | null; retryable?: boolean; details?: any }

export type JobStatus = "queued" | "running" | "awaiting_approval" | "completed" | "failed" | "cancelled";

export interface Approval {
  id: string; job_id: string; website_id: string; website_name?: string | null; step_key: string; action: string;
  description: string; details: any; status: string; requested_at: string; decided_at: string | null;
}

export interface Job {
  id: string; website_id: string; website_name: string | null; type: string; status: JobStatus; current_step: string | null;
  progress: number; error: string | null; attempts: number; worker_id: string | null; created_at: string;
  started_at: string | null; finished_at: string | null; steps?: JobStep[]; approvals?: Approval[]; last_event_id?: number;
}

export interface JobEvent {
  id?: number; type: string; job_id: string; website_id: string; step: string | null; level: string; message: string;
  data: any; progress?: number; ts: string;
}

export interface Deployment { id: string; version: number; status: string; provider: string; url: string | null; quality_score: number | null; created_at: string; details: any }

export interface Notification { id: string; title: string; message: string; level: "info" | "success" | "warning" | "error"; link: string | null; read: boolean; created_at: string }

export interface StackInfo { key: string; name: string; intended_use: string; description: string; deploy_model: string; status: string; versions: string[] }
export interface ProviderInfo { key: string; name: string; description: string; requires_approval?: boolean; credential_fields?: string[]; enabled: boolean; disabled_reason?: string; external?: boolean; kind?: string; can_register?: boolean }
export interface Policy { auto_publish: boolean; approval_domain_purchase: boolean; approval_dns_changes: boolean; domain_max_price: number; domain_years: number; domain_auto_renew: boolean; public_server: boolean; sandbox: boolean }
export interface Catalog { stacks: StackInfo[]; hosting: ProviderInfo[]; dns: ProviderInfo[]; agents: { key: string; title: string; agent: string; description: string }[]; policy: Policy }

export interface DomainQuote { domain: string; available: boolean; premium?: boolean; price: number | null; renewal_price: number | null; currency: string | null; reason?: string | null; within_cap: boolean; in_use: boolean; buyable: boolean }
export interface DomainRecord { id: string; name: string; provider: string; status: string; price: number | null; renewal_price: number | null; currency: string | null; years: number; auto_renew: boolean; expires_at: string | null; error: string | null; order_ref: string | null; website_id: string | null; website_name: string | null; created_at: string; updated_at: string | null }

export interface ProviderAccount { id: string; provider: string; kind: string; label: string; meta: any; max_sites: number | null; status: string; used_sites: number; credentials: Record<string, string>; created_at: string }
