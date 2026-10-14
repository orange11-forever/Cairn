import { matchesComponentSchema, type components } from '@cairn/sdk';
import { ApiError } from './errors.ts';
import { knowledgeContractError } from './knowledgeRequest.ts';

export type StreamParagraph = components['schemas']['KnowledgeAnswerParagraph'];
type Conversation = components['schemas']['KnowledgeConversationResponse'];
type Options = {
  conversationId: string;
  turnId: string;
  signal: AbortSignal;
  onParagraph(paragraph: StreamParagraph): void;
  validateComplete(value: Conversation): boolean;
};

export async function consumeConversationStream(response: Response, options: Options): Promise<Conversation> {
  const context = 'POST conversation stream';
  const invalid = () => knowledgeContractError(context);
  if (!response.headers.get('content-type')?.toLowerCase().startsWith('text/event-stream') || response.body === null) throw invalid();
  const reader = response.body.getReader();
  const abort = () => { void reader.cancel().catch(() => undefined); };
  options.signal.addEventListener('abort', abort, { once: true });
  const decoder = new TextDecoder('utf-8', { fatal: true });
  const paragraphs: StreamParagraph[] = [];
  let pending = '';
  let data: string[] = [];
  let bytes = 0;
  try {
    while (true) {
      options.signal.throwIfAborted();
      const result = await reader.read();
      options.signal.throwIfAborted();
      if (result.done) { try { decoder.decode(); } catch { throw invalid(); } throw invalid(); }
      bytes += result.value.byteLength;
      if (bytes > 8 * 1024 * 1024) throw invalid();
      try { pending += decoder.decode(result.value, { stream: true }); } catch { throw invalid(); }
      let newline: number;
      while ((newline = pending.indexOf('\n')) !== -1) {
        const line = pending.slice(0, newline).replace(/\r$/, '');
        pending = pending.slice(newline + 1);
        if (line.startsWith(':')) continue;
        if (line.startsWith('data:')) { data.push(line.slice(5).replace(/^ /, '')); continue; }
        if (line !== '') throw invalid();
        if (data.length === 0) continue;
        let value: unknown;
        try { value = JSON.parse(data.join('\n')) as unknown; } catch { throw invalid(); }
        data = [];
        if (!matchesComponentSchema('KnowledgeConversationStreamEvent', value) || value.conversationId !== options.conversationId || value.turnId !== options.turnId) throw invalid();
        options.signal.throwIfAborted();
        if (value.type === 'paragraph') {
          if (value.index !== paragraphs.length || paragraphs.length >= 8 || value.paragraph.text.trim() === '' || !value.paragraph.citationIds.every(id => /^S[1-6]$/.test(id)) || new Set(value.paragraph.citationIds).size !== value.paragraph.citationIds.length || paragraphs.reduce((n, p) => n + [...p.text].length, 0) + [...value.paragraph.text].length > 6000) throw invalid();
          paragraphs.push(value.paragraph);
          options.onParagraph(value.paragraph);
        } else if (value.type === 'error') {
          const traceId = response.headers.get('X-Request-ID');
          if (traceId !== null && value.traceId !== traceId) throw invalid();
          const retry = value.retryAfter !== null && value.retryAfter !== undefined && /^\d+$/.test(value.retryAfter) ? Number(value.retryAfter) : null;
          throw new ApiError('http', value.message, { status: value.status, code: value.code, traceId: value.traceId, retryAfterSeconds: retry !== null && Number.isSafeInteger(retry) && retry > 0 ? retry : null, context });
        } else {
          if (!options.validateComplete(value.conversation)) throw invalid();
          const turn = value.conversation.turns.find(item => item.id === options.turnId);
          if (paragraphs.length > 0 && (turn?.answer === null || turn?.answer === undefined || turn.answer.paragraphs.length !== paragraphs.length || !paragraphs.every((paragraph, index) => {
            const final = turn.answer!.paragraphs[index];
            return final !== undefined && final.text === paragraph.text && final.citationIds.length === paragraph.citationIds.length && final.citationIds.every((id, i) => id === paragraph.citationIds[i]);
          }))) throw invalid();
          return value.conversation;
        }
      }
    }
  } finally {
    options.signal.removeEventListener('abort', abort);
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
