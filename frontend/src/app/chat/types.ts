export type ApiResponse<T> = {
  code: number;
  message: string;
  data: T | null;
};

export type CompletionFinishReason = "stop" | "interrupt";

export type Conversation = {
  id: string;
  title: string;
  status: string;
  created_at: string;
  updated_at: string;
};

export type ChatMessage = {
  id: string;
  conversation_id?: string;
  parent_message_id?: string | null;
  role: string;
  content: string;
  rag_references?: RagReference[];
  created_at: string;
  pending?: boolean;
  failed?: boolean;
};

export type RagReference = {
  sourceType?: string;
  citationId: string;
  docId: string;
  chunkId: string;
  fileName?: string;
  url?: string;
  rerankScore?: number;
};

export type TraceStep = {
  node: string;
  status: "started" | "completed";
};

export type RagEvidenceItem = {
  source_type: "DOCUMENT";
  citation_id: string;
  content: string;
  doc_id: string;
  chunk_id: string;
  file_name?: string | null;
  url?: string | null;
  rerank_score?: number | null;
};

export type RagEvidence = {
  standalone_query: string;
  selected_retrievers: string[];
  evidence_items: RagEvidenceItem[];
};

export type ConversationPage = {
  items: Conversation[];
  next_cursor: string | null;
};

export type MessagePage = {
  items: ChatMessage[];
  next_cursor: string | null;
};
