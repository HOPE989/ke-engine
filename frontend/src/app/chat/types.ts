export type ApiResponse<T> = {
  code: number;
  message: string;
  data: T | null;
};

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
  created_at: string;
  pending?: boolean;
  failed?: boolean;
};

export type ConversationPage = {
  items: Conversation[];
  next_cursor: string | null;
};

export type MessagePage = {
  items: ChatMessage[];
  next_cursor: string | null;
};
