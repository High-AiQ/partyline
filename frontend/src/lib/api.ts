/** The REST surface, decoded once against the shared Zod contracts. */

import {
  AdapterImportResultSchema,
  AdapterSchema,
  ArchiveResultSchema,
  AttachmentSchema,
  ConversationDetailSchema,
  ConversationSchema,
  ImageUploadResponseSchema,
  OkResultSchema,
  PresetSchema,
  PurgeResultSchema,
  RunningProcessSchema,
  ScreenResultSchema,
  ShutdownResultSchema,
  ShutdownRequestSchema,
  RestartPlanSchema,
  RestartPlanRequestSchema,
  VersionInfoSchema,
  AuthLoginRequestSchema,
  AuthRegisterRequestSchema,
  AuthTokenResponseSchema,
  AuthUserSchema,
  HandleUpdateRequestSchema,
} from "./contracts";
import type {
  Adapter,
  AdapterImportResult,
  ArchiveResult,
  Attachment,
  Conversation,
  ConversationDetail,
  ImageUploadResponse,
  OkResult,
  Preset,
  PurgeResult,
  RunningProcess,
  ScreenResult,
  ShutdownResult,
  RestartPlan,
  RestartPlanRequest,
  VersionInfo,
  AuthLoginRequest,
  AuthRegisterRequest,
  AuthTokenResponse,
  AuthUser,
  HandleUpdateRequest,
} from "./contracts";
import { request } from "./http";
export { ApiContractError, ApiError, request } from "./http";

export interface AttachPayload {
  name: string;
  adapter: string;
  command: string;
  cwd: string;
  update?: boolean;
}

export interface AttachmentCommandPayload {
  command: string;
}

export interface PresetDraft {
  id?: string;
  title: string;
  name: string;
  adapter: string;
  command: string;
}

export interface ImageUpload {
  files: readonly File[];
  body: string;
  title: string | null;
  description: string | null;
}

export interface PartylineApi {
  register(payload: AuthRegisterRequest): Promise<AuthTokenResponse>;
  login(payload: AuthLoginRequest): Promise<AuthTokenResponse>;
  me(): Promise<AuthUser>;
  changeHandle(payload: HandleUpdateRequest): Promise<AuthUser>;
  version(): Promise<VersionInfo>;
  running(): Promise<RunningProcess[]>;
  planRestart(plan: RestartPlanRequest): Promise<RestartPlan>;
  shutdown(plan?: RestartPlanRequest): Promise<ShutdownResult>;
  adapters(): Promise<Adapter[]>;
  importAdapters(repository: string, ref: string): Promise<AdapterImportResult>;
  conversations(archived?: boolean): Promise<Conversation[]>;
  conversation(id: string): Promise<ConversationDetail>;
  createConversation(name: string): Promise<Conversation>;
  renameConversation(id: string, name: string): Promise<Conversation>;
  setTopic(id: string, topic: string): Promise<Conversation>;
  archiveConversation(id: string): Promise<ArchiveResult>;
  restoreConversation(id: string): Promise<Conversation>;
  purgeConversation(id: string): Promise<PurgeResult>;
  uploadImages(conversationId: string, upload: ImageUpload): Promise<ImageUploadResponse>;
  attach(conversationId: string, payload: AttachPayload): Promise<Attachment>;
  editAttachmentCommand(attachmentId: string, payload: AttachmentCommandPayload): Promise<Attachment>;
  detach(attachmentId: string): Promise<OkResult>;
  resume(attachmentId: string): Promise<Attachment>;
  screen(attachmentId: string): Promise<ScreenResult>;
  sendKey(attachmentId: string, key: string): Promise<OkResult>;
  presets(): Promise<Preset[]>;
  savePreset(preset: PresetDraft): Promise<Preset>;
  deletePreset(id: string): Promise<OkResult>;
}

export const api: PartylineApi = {
  register: (payload) =>
    request("/api/auth/register", {
      schema: AuthTokenResponseSchema,
      method: "POST",
      body: AuthRegisterRequestSchema.parse(payload),
      fallback: "could not create your account",
      skipRefresh: true,
    }),
  login: (payload) =>
    request("/api/auth/login", {
      schema: AuthTokenResponseSchema,
      method: "POST",
      body: AuthLoginRequestSchema.parse(payload),
      fallback: "could not sign in",
      skipRefresh: true,
    }),
  me: () => request("/api/auth/me", { schema: AuthUserSchema }),
  changeHandle: (payload) =>
    request("/api/auth/me", {
      schema: AuthUserSchema,
      method: "PATCH",
      body: HandleUpdateRequestSchema.parse(payload),
      fallback: "could not change your handle",
    }),
  version: () => request("/api/version", { schema: VersionInfoSchema }),
  running: () => request("/api/running", { schema: RunningProcessSchema.array() }),
  planRestart: (plan) =>
    request("/api/restart-plan", {
      schema: RestartPlanSchema,
      method: "POST",
      body: RestartPlanRequestSchema.parse(plan),
      fallback: "could not schedule process reattachment",
    }),
  shutdown: (plan) =>
    request("/api/shutdown", {
      schema: ShutdownResultSchema,
      method: "POST",
      body: ShutdownRequestSchema.parse(plan ? { reattach: RestartPlanRequestSchema.parse(plan) } : {}),
      fallback: "could not stop partyline",
    }),

  adapters: () => request("/api/adapters", { schema: AdapterSchema.array() }),
  importAdapters: (repository, ref) =>
    request("/api/adapters/import", {
      schema: AdapterImportResultSchema,
      method: "POST",
      body: { repository, ref: ref || null },
      fallback: "import failed",
    }),

  conversations: (archived = false) =>
    request(`/api/conversations${archived ? "?archived=1" : ""}`, {
      schema: ConversationSchema.array(),
    }),
  conversation: (id) => request(`/api/conversations/${id}`, { schema: ConversationDetailSchema }),
  createConversation: (name) =>
    request("/api/conversations", { schema: ConversationSchema, method: "POST", body: { name } }),
  renameConversation: (id, name) =>
    request(`/api/conversations/${id}/name`, {
      schema: ConversationSchema,
      method: "PUT",
      body: { name },
      fallback: "could not rename line",
    }),
  setTopic: (id, topic) =>
    request(`/api/conversations/${id}/topic`, {
      schema: ConversationSchema,
      method: "PUT",
      body: { topic },
      fallback: "could not save topic",
    }),
  archiveConversation: (id) =>
    request(`/api/conversations/${id}`, {
      schema: ArchiveResultSchema,
      method: "DELETE",
      fallback: "could not delete line",
    }),
  restoreConversation: (id) =>
    request(`/api/conversations/${id}/restore`, {
      schema: ConversationSchema,
      method: "POST",
      fallback: "could not restore line",
    }),
  purgeConversation: (id) =>
    request(`/api/conversations/${id}/purge`, {
      schema: PurgeResultSchema,
      method: "DELETE",
      fallback: "could not delete forever",
    }),
  uploadImages: (conversationId, upload) => {
    const form = new FormData();
    for (const file of upload.files) form.append("file", file);
    if (upload.body) form.append("body", upload.body);
    if (upload.title) form.append("title", upload.title);
    if (upload.description) form.append("description", upload.description);
    return request(`/api/conversations/${conversationId}/images`, {
      schema: ImageUploadResponseSchema,
      method: "POST",
      form,
      fallback: "image upload failed",
    });
  },

  attach: (conversationId, payload) =>
    request(`/api/conversations/${conversationId}/attachments`, {
      schema: AttachmentSchema,
      method: "POST",
      body: payload,
      fallback: "attach failed",
    }),
  editAttachmentCommand: (attachmentId, payload) =>
    request(`/api/attachments/${attachmentId}`, {
      schema: AttachmentSchema,
      method: "PATCH",
      body: payload,
      fallback: "could not save command",
    }),
  detach: (attachmentId) =>
    request(`/api/attachments/${attachmentId}`, {
      schema: OkResultSchema,
      method: "DELETE",
      fallback: "could not detach",
    }),
  resume: (attachmentId) =>
    request(`/api/attachments/${attachmentId}/resume`, {
      schema: AttachmentSchema,
      method: "POST",
      fallback: "resume failed",
    }),
  screen: (attachmentId) =>
    request(`/api/attachments/${attachmentId}/screen`, {
      schema: ScreenResultSchema,
      fallback: "attachment is not live",
    }),
  sendKey: (attachmentId, key) =>
    request(`/api/attachments/${attachmentId}/keys`, {
      schema: OkResultSchema,
      method: "POST",
      body: { key },
      fallback: "could not send key",
    }),

  presets: () => request("/api/presets", { schema: PresetSchema.array() }),
  savePreset: (preset) =>
    preset.id
      ? request(`/api/presets/${preset.id}`, {
          schema: PresetSchema,
          method: "PUT",
          body: preset,
          fallback: "save failed",
        })
      : request("/api/presets", {
          schema: PresetSchema,
          method: "POST",
          body: preset,
          fallback: "save failed",
        }),
  deletePreset: (id) =>
    request(`/api/presets/${id}`, {
      schema: OkResultSchema,
      method: "DELETE",
      fallback: "could not delete preset",
    }),
};
