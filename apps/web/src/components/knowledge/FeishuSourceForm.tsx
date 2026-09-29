import { useEffect, useState, type FormEvent } from "react";

import type { FeishuSourceCreate, FeishuSourcePatch, KnowledgeSource } from "../../api/knowledgeSources.ts";
import { FEISHU_INTERVALS, parseFeishuDocumentId } from "../../lib/feishuDocument.ts";
import { FormField, fieldAria } from "../FormField.tsx";

type Props = {
  source: KnowledgeSource | null;
  pending: boolean;
  error: string | null;
  onCancel(): void;
  onCreate(body: FeishuSourceCreate): void;
  onUpdate(body: FeishuSourcePatch): void;
};

function validName(value: string): boolean {
  const trimmed = value.trim();
  return trimmed.length > 0 && trimmed.length <= 200 &&
    !/[\u0000-\u001f\u007f-\u009f]/.test(trimmed);
}
const validAlias = (value: string) => /^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(value);

export function FeishuSourceForm({ source, pending, error, onCancel, onCreate, onUpdate }: Props) {
  const [name, setName] = useState(source?.name ?? "");
  const [documentInput, setDocumentInput] = useState(source?.documentId ?? "");
  const [credentialRef, setCredentialRef] = useState(source?.credentialRef ?? "");
  const [interval, setIntervalValue] = useState(source?.syncIntervalSeconds === null || source === null
    ? "manual" : String(source.syncIntervalSeconds));
  const [shared, setShared] = useState(false);
  const [touched, setTouched] = useState(false);
  useEffect(() => {
    setName(source?.name ?? ""); setDocumentInput(source?.documentId ?? "");
    setCredentialRef(source?.credentialRef ?? "");
    setIntervalValue(source?.syncIntervalSeconds === null || source === null
      ? "manual" : String(source.syncIntervalSeconds));
    setShared(false); setTouched(false);
  }, [source?.id, source?.name, source?.credentialRef, source?.syncIntervalSeconds, source?.documentId]);
  const documentId = source === null ? parseFeishuDocumentId(documentInput) : source.documentId;
  const nameError = !validName(name) ? "请输入 1 至 200 字的来源名称，且不要使用控制字符" : null;
  const documentError = documentId === null ? "请输入新版飞书文档 ID，或 feishu.cn 的 HTTPS /docx/ 链接" : null;
  const aliasError = !validAlias(credentialRef) ? "请输入部署管理员配置的凭证别名（字母开头，最多 64 位）" : null;
  const seconds = interval === "manual" ? null : Number(interval);
  const intervalError = seconds !== null && (!Number.isInteger(seconds) || seconds < 300 || seconds > 604800)
    ? "同步周期须在 300 至 604800 秒之间" : null;
  const changed = source === null || name.trim() !== source.name || credentialRef !== source.credentialRef ||
    seconds !== source.syncIntervalSeconds;
  const requiresSharing = source === null || credentialRef !== source.credentialRef;
  const valid = nameError === null && documentError === null && aliasError === null && intervalError === null &&
    changed && (!requiresSharing || shared);
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setTouched(true);
    if (!valid || pending || documentId === null) return;
    if (source === null) {
      onCreate({ name: name.trim(), documentId, credentialRef, syncIntervalSeconds: seconds,
        accessPolicy: "project_members" });
    } else {
      const renamed = name.trim() !== source.name;
      const periodChanged = seconds !== source.syncIntervalSeconds;
      if (credentialRef !== source.credentialRef) {
        const body: FeishuSourcePatch = { credentialRef, accessPolicy: "project_members" };
        if (renamed) body.name = name.trim();
        if (periodChanged) body.syncIntervalSeconds = seconds;
        onUpdate(body);
      } else if (renamed) {
        const body: FeishuSourcePatch = { name: name.trim() };
        if (periodChanged) body.syncIntervalSeconds = seconds;
        onUpdate(body);
      } else {
        onUpdate({ syncIntervalSeconds: seconds });
      }
    }
  }
  const existingInterval = source !== null && source.syncIntervalSeconds !== null &&
    !FEISHU_INTERVALS.some((option) => option.value === String(source.syncIntervalSeconds));
  return <section aria-label={source === null ? "添加飞书来源" : "编辑飞书来源"} className="feishu-source-form-region">
    <h2>{source === null ? "添加飞书来源" : `编辑 ${source.name}`}</h2>
    <p>文档先登记，再由同步任务读取并建立索引。</p>
    <form noValidate onSubmit={submit}>
      <FormField id="feishu-source-name" label="来源名称" error={touched ? nameError : null}>
        <input id="feishu-source-name" autoComplete="off" maxLength={200} value={name}
          onChange={(event) => setName(event.target.value)} disabled={pending}
          {...fieldAria("feishu-source-name", touched ? nameError : null)} />
      </FormField>
      <FormField id="feishu-document" label="飞书文档链接或 ID" error={touched ? documentError : null}
        hint={source === null ? "仅支持飞书新版文档（docx）；链接只在本地解析。" : "已登记的文档 ID 不可修改。"}>
        <input id="feishu-document" autoComplete="off" value={documentInput}
          onChange={(event) => setDocumentInput(event.target.value)} disabled={pending || source !== null}
          {...fieldAria("feishu-document", touched ? documentError : null, true)} />
      </FormField>
      <FormField id="feishu-credential" label="凭证别名" error={touched ? aliasError : null}
        hint="由部署管理员配置的连接名称；不要在此输入密钥。">
        <input id="feishu-credential" autoComplete="off" value={credentialRef}
          onChange={(event) => { setCredentialRef(event.target.value); setShared(false); }} disabled={pending}
          {...fieldAria("feishu-credential", touched ? aliasError : null, true)} />
      </FormField>
      <FormField id="feishu-interval" label="同步周期" error={touched ? intervalError : null}>
        <select id="feishu-interval" value={interval} onChange={(event) => setIntervalValue(event.target.value)}
          disabled={pending} {...fieldAria("feishu-interval", touched ? intervalError : null)}>
          {FEISHU_INTERVALS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          {existingInterval && source !== null ? <option value={String(source.syncIntervalSeconds)}>每 {source.syncIntervalSeconds} 秒（当前值）</option> : null}
        </select>
      </FormField>
      {requiresSharing ? <label className="feishu-share-confirm">
        <input type="checkbox" checked={shared} disabled={pending}
          onChange={(event) => setShared(event.target.checked)} />
        <span>我确认将此文档共享给当前项目中有读取权限的成员</span>
      </label> : null}
      {touched && requiresSharing && !shared ? <p role="alert" className="field-error">请确认项目共享范围</p> : null}
      {error ? <p role="alert" className="form-error">{error}</p> : null}
      <div className="feishu-form-actions">
        <button type="button" onClick={onCancel} disabled={pending}>取消</button>
        <button type="submit" className="primary-btn" disabled={!valid || pending}>
          {pending ? "正在保存…" : source === null ? "添加来源" : "保存修改"}
        </button>
      </div>
    </form>
  </section>;
}
