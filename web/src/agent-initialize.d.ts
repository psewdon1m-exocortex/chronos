export interface InitializationJob {
  id?: string; job_id?: string; request_id?: string; state: string; message?: string; error?: string;
  progress?: { mode: string; completed?: number; total?: number };
}
export interface AgentInitializationOptions {
  component: string; service: string; description: string; profile?: string; codeLabel?: string; theme?: string;
  initialize: (input: { request_id: string; enrollment_code?: string }) => Promise<InitializationJob>;
  observe: (id?: string) => Promise<InitializationJob>;
  recover?: (hint?: { id?: string; request_id?: string } | null) => Promise<InitializationJob | undefined | null>;
  verify: () => Promise<{ ready: boolean; message?: string }>;
  onComplete?: () => void | Promise<void>;
}
export function openAgentInitialization(options: AgentInitializationOptions): () => void;
export function confirmAgentAction(options: { title: string; message: string; confirmLabel: string; theme?: string }): Promise<boolean>;
