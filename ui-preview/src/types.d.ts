// Backend contracts, mirrored read-only from the services. Source of truth:
// shared/schemas.py, proposal/schemas.py, proposal/main.py, ingestion/utils/schema.py,
// shared/errors.py, detection/main.py. Keep field names and literals identical.

/* ------------------------------------------------------------ Detection */

export type TenderStatus = 'new' | 'incomplete' | 'processed' | 'archived';
export type TenderSource = 'simulated_feed' | 'manual' | 'TED' | 'SAM';

/** detection/normalize.py quality codes; `possible_duplicate_of:<id>` carries an id. */
export type QualityWarning =
  | 'missing_deadline'
  | 'deadline_in_past'
  | 'sanitized_chars'
  | 'llm_unavailable'
  | 'unknown_fields'
  | 'no_raw_text'
  | 'text_too_short'
  | 'text_mostly_symbols'
  | 'requirements_capped'
  | 'requirements_trimmed'
  | `possible_duplicate_of:${string}`;

export interface DataQuality {
  completeness: number;
  missing_fields: string[];
  warnings: string[];
  is_expired: boolean;
}

export interface Tender {
  id: string;
  title: string;
  issuer: string;
  /** One of CAPABILITY_TAXONOMY, or "unknown". */
  sector: string;
  requirements: string[];
  /** ISO date; null degrades the record to `incomplete`. */
  deadline: string | null;
  raw_text: string;
  source: TenderSource;
  detected_at: string;
  status: TenderStatus;
  quality: DataQuality;
  /** Notice details kept at detection; absent on tenders stored before S8. */
  issuer_country?: string | null;
  notice_type?: string | null;
  /** ISO date. */
  published_at?: string | null;
  /** http(s) document links, at most 20. */
  links?: string[];
}

/** POST /tenders/ingest body. Title and issuer are required; the rest degrade quality. */
export interface IngestPayload {
  title: string;
  issuer: string;
  deadline?: string;
  requirements?: string[];
  raw_text?: string;
  source?: TenderSource;
}

/** POST /tenders/seed */
export interface SeedResult {
  seeded: number;
  tenders: Array<
    | { file: string; id: string; title: string; existing: boolean; status: 'success' }
    | { file: string; status: 'error'; error: string }
  >;
}

/* ------------------------------------------------------------ Ingestion */

export interface TedLinks {
  pdfs: Record<string, string>;
  html: Record<string, string>;
}

export interface Notice {
  id: string;
  title: string;
  raw_text: string;
  requirements: string[] | null;
  issuer: string;
  issuer_country: string;
  source: 'simulated_feed' | 'TED' | 'SAM';
  notice_type: string;
  deadline: string;
  published_at: string;
  /** TED: English PDF/HTML links. SAM: attachment URLs. */
  links: TedLinks | string[];
}

/** POST /ingest/TED and POST /ingest/SAM {page}. Not stored: each notice is then posted to detection. */
export interface MappedBatch {
  notices: Notice[];
  page_cap: number;
}

/* ------------------------------------------------------------- Research */

export type ResearchStatus = 'complete' | 'partial' | 'unavailable';
export type Confidence = 'low' | 'medium' | 'high';

export type ResearchFactCategory = 'sector' | 'estimated_revenue' | 'past_projects' | 'key_partners';

export interface ResearchFact {
  value: string;
  category: ResearchFactCategory;
  confidence: Confidence;
  /** The page the runner fetched the fact from. */
  source: string;
}

export interface ProspectResearch {
  tender_id: string;
  issuer: string;
  sector: string | null;
  estimated_revenue: string | null;
  past_projects: string[];
  key_partners: string[];
  notes: string;
  /** Computed by research/runner.py from distinct sources, never by the model. */
  confidence: Confidence;
  /** Only URLs that contributed a fact. */
  sources: string[];
  status: ResearchStatus | null;
  completed_at: string | null;
  /** Empty for research stored before per-fact sources. */
  facts: ResearchFact[];
}

/** One audit-log line of a research run. `content` is untrusted web text, cut to 300 characters. */
export interface AuditEntry {
  timestamp: string;
  tool: string;
  params: Record<string, unknown>;
  hash: string;
  content: string;
}

export interface ResearchAudit {
  run_id: string | null;
  entries: AuditEntry[];
}

/* ------------------------------------------------------------------ RAG */

export type DocType = 'cv' | 'project' | 'tool';

/** GET /api/library/stats: records per type (one first chunk each). */
export type LibraryStats = Record<DocType, number>;

export interface QueryRequest {
  /** 3 to 10,000 characters. */
  text: string;
  /** 1 to 20, default 5. */
  top_k?: number;
  doc_type?: DocType | null;
  /** 0 to 1, default 0. */
  similarity_threshold?: number;
}

export interface QueryResult {
  id?: string;
  content: string;
  doc_type: DocType;
  source_file?: string;
  metadata: {
    record_id: string;
    person?: string;
    role?: string;
    project_name?: string;
    client_sector?: string;
    tech_stack?: string[];
    [key: string]: unknown;
  };
  similarity: number;
  ranking_score: number;
}

/* ------------------------------------------------------------- Proposal */

export type Fit = 'Strong' | 'Partial' | 'Gap';

export interface Meta {
  buyer: string;
  tender_title: string;
  reference: string;
  date: string;
  /** max 60 */
  headline: string;
  /** max 80 */
  subtitle: string;
  sample: boolean;
}

export interface RequirementRow {
  requirement: string;
  evidence: string;
  /** 0..1 RAG similarity; Strong >= 0.55, Partial >= 0.40. */
  score: number;
  /** null: nothing was retrieved. */
  evidence_id: string | null;
}

export interface Proposal {
  meta: Meta;
  signatory: { name: string; role: string; contact: string };
  letter: { salutation: string; paragraphs: string[]; closing: string; title: string };
  summary: {
    title: string;
    pillars: Array<{ title: string; body: string; evidence: string[] }>;
    why_us: string;
  };
  buyer: {
    profile: { sector: string; estimated_revenue: string; key_partners: string };
    needs: Array<{ title: string; body: string }>;
    researched: boolean;
  };
  requirements: RequirementRow[];
  all_requirements: RequirementRow[];
  approach: { title: string; phases: Array<{ name: string; weeks: number; body: string }>; milestones: string };
  team: Array<{ cv_id: string | null; name: string; role: string; years: number | null; skills: string; score: number }>;
  references: Array<{
    project_id: string | null;
    title: string;
    summary: string;
    sector: string;
    score: number;
    delivered: boolean | null;
  }>;
  investment: {
    currency: string;
    lines: Array<{ workstream: string; days: number | null; amount: number | null }>;
    note: string;
    next_steps: Array<{ title: string; detail: string }>;
  };
  input_warnings: string[];
  /** Field paths filled by a formula (proposal/estimate.py). */
  estimated: string[];
}

export interface NoBid {
  meta: Meta;
  requirements: RequirementRow[];
  all_requirements: RequirementRow[];
  warnings: string[];
  recommendation: string;
}

export interface TraceStep {
  step: string;
  attempts: number;
  ok: boolean;
  failures: unknown[];
  trimmed?: { field: string; from: number; to: number; how: string }[];
  unsupported?: { field: string; text: string }[];
  verifier?: { field: string; verdict: 'supported' | 'partial' | 'unsupported'; reason?: string }[] | { error: string };
}

export interface ProposalResult {
  tender_id: string;
  kind: 'proposal' | 'no_bid' | 'rejected';
  review_status?: 'draft' | 'accepted' | 'refused';
  deck: Proposal | NoBid | Partial<Proposal>;
  warnings: string[];
  artifacts: { pptx?: string | null; csv?: string | null; pdf?: string | null };
  /** What ran on this deck; empty for a result stored before the service reported it. */
  checks?: { verifier?: boolean; claim_check?: boolean };
  /** How each step ran; empty for a result stored before the service returned it. */
  trace?: TraceStep[];
  generated_at: string;
}

export type ReviewStatus = 'draft' | 'review' | 'approved' | 'work';

/** Reviewer state for one stored deck. The sign-off is a typed name, not an account. */
export interface Review {
  deck_generated_at: string;
  sections: Partial<Record<string, ReviewStatus>>;
  signed_off_by: string | null;
  signed_off_at: string | null;
}

/* Result of prompt-edit proposal */
export interface EditProposalResult{
  changed: boolean;
  updated: object;
}

/* 

class ProposalAcceptResult(BaseModel):
    tender_id: str
    # "rejected": the deck was composed but the validator refused the pptx for
    # slide/cell/palette issues; the composed deck and each issue come back so
    # the caller can show why instead of dead-ending in a 422.
    kind: Literal["proposal", "no_bid", "rejected"]
    deck: dict[str, object]
    warnings: list[str] = []
    artifacts: dict[str, str | None] = {}
    # What actually ran on this deck; {} for a result stored before checks were reported.
    checks: dict[str, bool] = {}
    # compose()'s per-step record; [] for a result stored before the trace was returned.
    trace: list[dict] = []
    generated_at: str
*/

export interface AcceptProposalResult{
  tender_id: string;

  // "rejected": the deck was composed but the validator refused the pptx for
  // slide/cell/palette issues; the composed deck and each issue come back so
  // the caller can show why instead of dead-ending in a 422.
  kind: "proposal" | "no_bid" | "rejected";

  deck: Record<string, unknown>;
  warnings?: string[];
  artifacts?: Record<string, string | null>;

  // What actually ran on this deck; {} for a result stored before checks were reported.
  checks?: Record<string, boolean>;

  // compose()'s per-step record; [] for a result stored before the trace was returned.
  trace?: Array<Record<string, unknown>>;

  generated_at: string;
}

/**
 * What a refusal changes: the stored row's review state. The deck itself,
 * its warnings and its artifact index stay exactly as they were saved.
 */
export interface RefuseProposalResult {
  tender_id: string;
  kind: "proposal" | "no_bid";
  review_status: "refused";
}

/* --------------------------------------------------------------- Errors */

export type ErrorCode =
  | 'UNAUTHORIZED'
  | 'NOT_FOUND'
  | 'BAD_REQUEST'
  | 'INTERNAL'
  | 'UPSTREAM_UNAVAILABLE'
  | 'TENDER_INVALID_FIELD'
  | 'TENDER_INVALID_DEADLINE'
  | 'TENDER_INVALID_REQUIREMENTS'
  | 'RAW_TEXT_TOO_LONG'
  | 'TENDER_BATCH_INVALID'
  | 'TENDER_BATCH_TOO_LARGE'
  | 'PAYLOAD_TOO_LARGE';

export interface ErrorEnvelope {
  error: { code: ErrorCode; message: string; field: string | null; retryable: boolean; request_id: string | null };
}

/** A captured response: HTTP status plus the envelope body. */
export interface CapturedError {
  status: number;
  request_id: string;
  body: ErrorEnvelope;
}

export type BudgetMethod = 'explicit' | 'comparables' | 'effort' | 'none';
export type InsightsStatus = 'complete' | 'partial' | 'unavailable';
export interface BudgetEstimate { currency: 'TND'; min: number | null; likely: number | null; max: number | null; method: BudgetMethod; assumptions: string[]; confidence: Confidence; sources: string[]; }
export interface Competitor { name: string; why_likely: string; strengths: string[]; weaknesses: string[]; evidence: string[]; }
export interface Positioning { olivesoft_advantages: string[]; risks: string[]; recommended_strategy: string; differentiators_to_emphasize: string[]; }
export interface TenderInsights { tender_id: string; issuer: string; budget: BudgetEstimate; competitors: Competitor[]; positioning: Positioning; notes: string; confidence: Confidence; status: InsightsStatus | null; completed_at: string | null; }
export interface InsightTraceStep { turn: number | null; action: string; args?: Record<string, unknown>; thought?: string; auto?: boolean; ok?: boolean; error?: string | null; result_preview?: string; seconds?: number; }
export interface InsightsRun { run_id: number | null; tender_id?: string; created_at?: string; status?: InsightsStatus | null; confidence?: Confidence; method?: BudgetMethod; stop_reason?: string; insights: TenderInsights; trace: InsightTraceStep[]; }

/* ---------------------------------------------------------------- Pipeline (n8n) */

export interface PipelineTally {
  tenders: number;
  researched: number;
  decks: number;
}

/** The last full-pipeline run started from the UI. `tracked` is false while n8n's status cannot be read. */
export interface PipelineRun {
  id: string | null;
  status: 'running' | 'success' | 'error' | 'unknown';
  tracked: boolean;
  error: CapturedError | null;
  workflowId: string | null;
  startedAt: number;
  stoppedAt: number | null;
  before: PipelineTally;
  /** Closed, or opened for review, once it finished. */
  seen: boolean;
}
