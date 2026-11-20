import { FileRefSchema, type FileRef } from "./contracts";
import { request } from "./http";

export function listFiles(conversationId: string): Promise<FileRef[]> {
  return request(`/api/conversations/${conversationId}/files`, { schema: FileRefSchema.array() });
}
