import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import type { StreamParagraph } from "../../api/conversationStreaming.ts";
import { ApiError } from "../../api/errors.ts";
import { appendKnowledgeConversationTurn, streamKnowledgeConversationTurn, createKnowledgeConversation, fetchKnowledgeAnswerModel, fetchKnowledgeConversation, fetchKnowledgeConversations, isConversationId, type KnowledgeConversation } from "../../api/knowledgeConversations.ts";
import { validateKnowledgeQuery } from "../../lib/knowledgeSearch.ts";
import { fetchAssistantSettings, fetchAssistants, fetchSkillCatalog, type AssistantSettings, type AssistantSettingsInput, type SkillSource, type SkillPreview, type SkillImportInput } from "../../api/assistantSkills.ts";

type Draft = { value: string; revision: number };
type Recovery = { conversationId: string; turnId: string | null; question: string; draftRevision: number; assistantRevision: number; skillId: string | null };
const NEW = "new";

function useConversationState({ organizationId, userId, projectId, generation, csrfToken, sessionSignal }: Scope) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const selectedId = params.get("conversation");
  const selected = useRef(selectedId); selected.current = selectedId;
  const scopeKey = ["project-knowledge", organizationId, projectId, "conversations", generation, userId] as const;
  const key = (id: string) => [...scopeKey, "detail", id] as const;
  const drafts = useRef(new Map<string, Draft>());
  const recoveries = useRef(new Map<string, Recovery>());
  const unverified = useRef(new Set<string>());
  const [accessDenied, setAccessDenied] = useState<ApiError | null>(null);
  const deniedRef = useRef<ApiError | null>(null);
  const action = useRef<{ controller: AbortController; conversationId: string } | null>(null);
  const [, renderState] = useState(0);
  const update = () => renderState(n => n + 1);
  const [preview, setPreview] = useState<StreamParagraph[]>([]);
  const [activity, setActivity] = useState<"send" | "read" | null>(null);
  const busy = activity !== null;
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [online, setOnline] = useState(() => navigator.onLine);
  const [showAllHistory, setShowAllHistory] = useState(false);
  const [selectedSkill, setSelectedSkill] = useState<string | null>(null);
  const [assistantDraft, setAssistantDraft] = useState<(AssistantSettingsInput & { assistantId: string | null }) | null>(null);
  const [assistantNeedsReload, setAssistantNeedsReload] = useState(false);
  const [importMode, setImportMode] = useState<SkillSource["type"]>("markdown");
  const [importSource, setImportSource] = useState<SkillSource | null>(null);
  const [importPreview, setImportPreview] = useState<SkillPreview | null>(null);
  const [pendingImport, setPendingImport] = useState<SkillImportInput | null>(null);
  const querySignal = (signal: AbortSignal) => AbortSignal.any([signal, sessionSignal]);
  const assistant = useQuery({ queryKey: [...scopeKey, "assistant-settings"], enabled: accessDenied === null, queryFn: ({ signal }) => fetchAssistantSettings({ projectId, signal: querySignal(signal) }), retry: false, gcTime: 0, refetchOnReconnect: false });
  const assistants = useQuery({ queryKey: [...scopeKey, "assistants"], enabled: accessDenied === null, queryFn: ({ signal }) => fetchAssistants({ projectId, signal: querySignal(signal) }), retry: false, gcTime: 0, refetchOnReconnect: false });
  const skills = useQuery({ queryKey: [...scopeKey, "skills"], enabled: accessDenied === null, queryFn: ({ signal }) => fetchSkillCatalog({ projectId, signal: querySignal(signal) }), retry: false, gcTime: 0, refetchOnReconnect: false });
  const list = useInfiniteQuery({ queryKey: [...scopeKey, "list", assistant.data?.id ?? null, showAllHistory], enabled: accessDenied === null && assistant.data !== undefined, initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => fetchKnowledgeConversations({ projectId, cursor: pageParam, currentAssistant: !showAllHistory, signal: querySignal(signal) }),
    getNextPageParam: page => page.nextCursor ?? undefined, retry: false, gcTime: 0, refetchOnReconnect: false });
  const model = useQuery({ queryKey: [...scopeKey, "model"], enabled: accessDenied === null, queryFn: ({ signal }) => fetchKnowledgeAnswerModel({ projectId, signal: querySignal(signal) }), retry: false, gcTime: 0, refetchOnReconnect: false });
  const activeModel = model.data?.models.find(item => item.id === (assistant.data?.modelId ?? model.data.defaultModelId));
  const modelReady = activeModel !== undefined && !model.isError && !model.isFetching;
  const detail = useQuery({ queryKey: key(selectedId ?? NEW), enabled: accessDenied === null && selectedId !== null && isConversationId(selectedId) && !recoveries.current.has(selectedId),
    queryFn: ({ signal }) => fetchKnowledgeConversation({ projectId, conversationId: selectedId!, signal: querySignal(signal) }),
    retry: false, gcTime: 0, staleTime: 0, refetchOnReconnect: false });
  const mutation = useMutation({ mutationFn: (operation: () => Promise<KnowledgeConversation>) => operation(), retry: false, networkMode: "always", gcTime: 0 });
  const newDraftKey = `${NEW}:${assistant.data?.id ?? "default"}`;
  const draftKey = selectedId ?? newDraftKey;
  const draft = drafts.current.get(draftKey)?.value ?? "";
  const recovery = selectedId === null ? undefined : recoveries.current.get(selectedId);

  function abortAction(message?: string) {
    action.current?.controller.abort(); action.current = null; setActivity(null); setPreview([]); mutation.reset();
    if (message !== undefined) setNotice(message);
  }
  useEffect(() => {
    const abort = () => { action.current?.controller.abort(); action.current = null; setPreview([]); };
    sessionSignal.addEventListener("abort", abort, { once: true });
    return () => {
      sessionSignal.removeEventListener("abort", abort); abort();
      void queryClient.cancelQueries({ queryKey: scopeKey }); queryClient.removeQueries({ queryKey: scopeKey });
      drafts.current.clear(); recoveries.current.clear(); unverified.current.clear();
    };
  }, [sessionSignal]);
  const previousId = useRef(selectedId);
  useLayoutEffect(() => {
    const old = previousId.current;
    if (old === selectedId) return;
    previousId.current = selectedId;
    if (action.current?.conversationId !== selectedId) abortAction();
    setError(null); setNotice(null);
    if (old !== null) { void queryClient.cancelQueries({ queryKey: key(old), exact: true }); queryClient.removeQueries({ queryKey: key(old), exact: true }); }
  }, [selectedId]);
  useEffect(() => {
    const status = () => { setOnline(navigator.onLine); if (!navigator.onLine) abortAction("当前离线；未完成的发送请在联网后重新读取会话。"); };
    window.addEventListener("online", status); window.addEventListener("offline", status);
    return () => { window.removeEventListener("online", status); window.removeEventListener("offline", status); };
  }, []);

  function setDraft(value: string) {
    const current = drafts.current.get(draftKey);
    drafts.current.set(draftKey, { value, revision: (current?.revision ?? 0) + 1 }); update();
  }
  function selectConversation(id: string | null, preserveDraft = false) {
    abortAction(); setError(null); setNotice(null);
    const next = new URLSearchParams(params); next.set("view", "chat");
    if (id === null) { next.delete("conversation"); if (!preserveDraft) drafts.current.set(newDraftKey, { value: "", revision: 0 }); }
    else next.set("conversation", id);
    selected.current = id;
    navigate({ pathname: `/projects/${projectId}/knowledge`, search: next.toString() }); update();
  }
  const previousAssistant = useRef<string | null | undefined>(undefined);
  useLayoutEffect(() => {
    if (assistant.data === undefined) return;
    const next = assistant.data.id ?? null;
    const previous = previousAssistant.current;
    previousAssistant.current = next;
    if (previous === undefined) {
      const early = drafts.current.get(`${NEW}:default`);
      if (early !== undefined && next !== null) { drafts.current.set(newDraftKey, early); drafts.current.delete(`${NEW}:default`); update(); }
      return;
    }
    if (previous !== next) {
      setSelectedSkill(null); setShowAllHistory(false); selectConversation(null, true);
    }
  }, [assistant.data?.id]);
  function start(id: string, kind: "send" | "read" = "send") {
    action.current?.controller.abort();
    const controller = new AbortController(); const current = { controller, conversationId: id }; action.current = current;
    const signal = querySignal(controller.signal);
    setActivity(kind); setPreview([]); setError(null); setNotice(null);
    return { signal, current, active: () => !signal.aborted && deniedRef.current === null && action.current === current && selected.current === id };
  }
  function clearSubmitted(token: Recovery) {
    const current = drafts.current.get(token.conversationId);
    if (current !== undefined && current.revision === token.draftRevision && current.value === token.question) drafts.current.set(token.conversationId, { value: "", revision: current.revision });
  }
  async function send() {
    if (deniedRef.current !== null || assistantNeedsReload || assistant.data === undefined || assistant.isError || assistant.isFetching || action.current !== null || sessionSignal.aborted || busy || recovery !== undefined || !online || !modelReady || (selectedId !== null && unverified.current.has(selectedId))) return;
    const validation = validateKnowledgeQuery(draft);
    if (!validation.ok) { setError(new Error(validation.message)); return; }
    let id = selectedId;
    const sourceDraft = drafts.current.get(draftKey) ?? { value: draft, revision: 0 };
    if (id !== null && (detail.data === undefined || detail.isFetching || detail.isError)) return;
    const createFirst = id === null;
    if (id === null) {
      id = crypto.randomUUID();
      const next = new URLSearchParams(params); next.set("conversation", id); next.set("view", "chat");
      selected.current = id;
      navigate({ pathname: `/projects/${projectId}/knowledge`, search: next.toString() }, { replace: true });
    }
    drafts.current.set(id, { value: validation.query, revision: sourceDraft.revision });
    const token: Recovery = { conversationId: id, turnId: createFirst ? null : crypto.randomUUID(), question: validation.query, draftRevision: sourceDraft.revision, assistantRevision: assistant.data.revision, skillId: selectedSkill };
    recoveries.current.set(id, token); update();
    const request = start(id);
    try {
      const response = await mutation.mutateAsync(async () => {
        let current = detail.data;
        if (createFirst) {
          current = await createKnowledgeConversation({ projectId, id, csrfToken, signal: request.signal });
          if (!request.active()) throw new ApiError("aborted", "请求已被取消");
          queryClient.setQueryData(key(id), current);
          token.turnId = crypto.randomUUID();
        }
        if (current === undefined || token.turnId === null) throw new ApiError("contract", "对话状态无效，请重新读取会话");
        const input = { projectId, conversationId: id, id: token.turnId, expectedRevision: current.revision, question: validation.query, assistantRevision: token.assistantRevision, skillId: token.skillId, csrfToken, signal: request.signal };
        return activeModel?.protocol === "openai-responses"
          ? streamKnowledgeConversationTurn({ ...input, onParagraph: paragraph => { if (request.active()) setPreview(previous => [...previous, paragraph]); } })
          : appendKnowledgeConversationTurn(input);
      });
      if (!request.active()) return;
      queryClient.setQueryData(key(id), response); unverified.current.delete(id); clearSubmitted(token); recoveries.current.delete(id);
      void list.refetch(); update();
    } catch (failure) {
      if (!request.active()) return;
      if (failure instanceof ApiError && failure.status === 404) unverified.current.add(id);
      setError(failure);
      setNotice(failure instanceof ApiError && failure.status === 409 ? "对话或资料已变化，请重新读取会话后再发送。" : "发送结果尚未确认，请重新读取会话；不会自动重发。 ");
    } finally { if (request.active()) { action.current = null; setActivity(null); setPreview([]); } }
  }
  async function reread() {
    if (deniedRef.current !== null || selectedId === null || !isConversationId(selectedId) || !online) return;
    const id = selectedId; unverified.current.add(id); update();
    const token = recoveries.current.get(id); const request = start(id, "read");
    await queryClient.cancelQueries({ queryKey: key(id), exact: true });
    try {
      let latestAssistant: AssistantSettings | undefined;
      const response = await mutation.mutateAsync(async () => {
        const [conversation, settings, models] = await Promise.all([fetchKnowledgeConversation({ projectId, conversationId: id, signal: request.signal }), fetchAssistantSettings({ projectId, signal: request.signal }), fetchKnowledgeAnswerModel({ projectId, signal: request.signal })]);
        if (request.active()) queryClient.setQueryData([...scopeKey, "model"], models);
        latestAssistant = settings; return conversation;
      });
      if (!request.active()) return;
      let recovered = false;
      if (token?.turnId !== null && token?.turnId !== undefined) {
        const found = response.turns.find(turn => turn.id === token.turnId);
        if (found !== undefined && (found.question !== token.question || (found.assistantRevision ?? 0) !== token.assistantRevision || (found.skillId ?? null) !== token.skillId)) throw new ApiError("contract", "已保存的问题或技能与请求不一致，请联系管理员");
        if (found !== undefined) { clearSubmitted(token); recovered = true; }
      }
      queryClient.setQueryData([...scopeKey, "assistant-settings"], latestAssistant);
      queryClient.setQueryData(key(id), response); unverified.current.delete(id); recoveries.current.delete(id);
      setNotice(token === undefined ? "会话已重新读取。" : recovered ? "已恢复保存的回答。" : "会话已重新读取，这个问题尚未保存，可以再次发送。"); update();
      void list.refetch();
    } catch (failure) { if (request.active()) { setError(failure); setNotice("重新读取失败，请保留草稿并再次读取会话。"); } }
    finally { if (request.active()) { action.current = null; setActivity(null); setPreview([]); } }
  }
  function invalidateHistory() {
    abortAction("资料已变化，正在重新核验历史回答。");
    if (selectedId !== null) {
      queryClient.setQueryData<KnowledgeConversation>(key(selectedId), current => current === undefined ? current : { ...current, turns: current.turns.map(turn => ({ ...turn, answer: null, answerUnavailable: true })) });
      void queryClient.invalidateQueries({ queryKey: key(selectedId), exact: true });
    }
  }
  const observedDenial = [list.error, model.error, assistant.error, assistants.error, skills.error].find((value): value is ApiError => value instanceof ApiError && value.status === 404) ?? null;
  const projectError = accessDenied ?? observedDenial;
  deniedRef.current = projectError;
  useEffect(() => {
    if (observedDenial === null || accessDenied !== null) return;
    setAccessDenied(observedDenial); abortAction();
    void queryClient.cancelQueries({ queryKey: scopeKey }); queryClient.removeQueries({ queryKey: scopeKey });
  }, [observedDenial, accessDenied]);
  const entries = projectError !== null ? [] : list.data?.pages.flatMap(page => page.items) ?? [];
  const historyVerified = projectError === null && selectedId !== null && !unverified.current.has(selectedId);
  useEffect(() => { if (selectedSkill !== null && assistant.data !== undefined && !assistant.data.enabledSkillIds.includes(selectedSkill)) { setSelectedSkill(null); setNotice("所选技能已停用，问题草稿已保留。"); } }, [assistant.data, selectedSkill]);
  function chooseSkill(id: string | null) { setSelectedSkill(id); const item = skills.data?.items.find(item => item.id === id); if (item !== undefined && !draft.trim()) setDraft(item.defaultQuestion); }
  function applyAssistant(value: AssistantSettings) { queryClient.setQueryData([...scopeKey, "assistant-settings"], value); }
  return { csrfToken, selectedId, selectConversation, draft, setDraft, send, reread, cancel: () => abortAction("已停止等待；服务端可能仍在处理，请重新读取会话。"), busy, activity, recovery, error, notice, online, detail, list, model, activeModel, entries, projectError, historyVerified, invalidateHistory, assistant, skills, selectedSkill, chooseSkill, assistantDraft, setAssistantDraft, importSource, setImportSource, importPreview, setImportPreview, pendingImport, setPendingImport, applyAssistant, importMode, setImportMode,
    assistants, assistantNeedsReload, setAssistantNeedsReload, showAllHistory, setShowAllHistory,
    preview: projectError === null && online && activity === "send" ? preview : [],
    canSend: projectError === null && !assistantNeedsReload && assistant.data !== undefined && !assistant.isError && !assistant.isFetching && online && !busy && recovery === undefined && modelReady && (selectedId === null || (historyVerified && detail.data !== undefined && !detail.isFetching && !detail.isError && detail.data.turns.length < 50 && detail.data.turns.every(turn => (turn.assistantId ?? null) === (assistant.data?.id ?? null)))) };
}
interface Scope { organizationId: string; userId: string; projectId: string; generation: number; csrfToken: string; sessionSignal: AbortSignal }
const Context = createContext<ReturnType<typeof useConversationState> | null>(null);
export function ProjectConversationsProvider({ children, ...scope }: Scope & { children: ReactNode }) {
  const state = useConversationState(scope);
  return <Context.Provider value={state}>{children}</Context.Provider>;
}
export const useProjectConversations = () => useContext(Context);
