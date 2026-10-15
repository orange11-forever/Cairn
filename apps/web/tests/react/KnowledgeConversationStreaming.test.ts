import { afterEach, expect, test, vi } from 'vitest';
import { consumeConversationStream } from '../../src/api/conversationStreaming.ts';

const cid = '00000000-0000-4000-8000-000000000001';
const tid = '00000000-0000-4000-8000-000000000002';
const paragraph = { text: '第一段。', citationIds: ['S1'] };
const event = { type: 'paragraph', conversationId: cid, turnId: tid, index: 0, paragraph };
const error = { type: 'error', conversationId: cid, turnId: tid, status: 503, code: 'answer_unavailable', message: '生成式回答暂时不可用', traceId: 'trace', retryAfter: null };
const wire = (value: object) => new TextEncoder().encode(`data: ${JSON.stringify(value)}\n\n`);
afterEach(() => vi.restoreAllMocks());

test('real stream exposes a paragraph while upstream remains open then surfaces safe terminal error', async () => {
  let release!: () => void;
  const wait = new Promise<void>(resolve => { release = resolve; });
  const receive = vi.fn(() => release());
  const response = new Response(new ReadableStream({ async start(controller) { controller.enqueue(wire(event)); await wait; controller.enqueue(wire(error)); controller.close(); } }), { headers: { 'Content-Type': 'text/event-stream' } });
  await expect(consumeConversationStream(response, { conversationId: cid, turnId: tid, signal: new AbortController().signal, onParagraph: receive, validateComplete: () => false })).rejects.toMatchObject({ kind: 'http', status: 503, traceId: 'trace' });
  expect(receive).toHaveBeenCalledWith(paragraph);
});

test.each([{ ...event, turnId: cid }, { ...event, index: 1 }, { ...event, extra: true }])('rejects wrong IDs, order and extra fields before preview', async value => {
  vi.spyOn(console, 'error').mockImplementation(() => undefined);
  const receive = vi.fn();
  const response = new Response(new ReadableStream({ start(controller) { controller.enqueue(wire(value)); controller.close(); } }), { headers: { 'Content-Type': 'text/event-stream' } });
  await expect(consumeConversationStream(response, { conversationId: cid, turnId: tid, signal: new AbortController().signal, onParagraph: receive, validateComplete: () => false })).rejects.toMatchObject({ kind: 'contract' });
  expect(receive).not.toHaveBeenCalled();
});

test.each(['truncated', 'invalid-utf8', 'unknown-citation'])('clears the transport path on %s with a contract error', async failure => {
  vi.spyOn(console, 'error').mockImplementation(() => undefined);
  const response = new Response(new ReadableStream({ start(controller) {
    if (failure === 'invalid-utf8') controller.enqueue(new Uint8Array([255]));
    else controller.enqueue(wire(failure === 'unknown-citation' ? { ...event, paragraph: { ...paragraph, citationIds: ['S99'] } } : event));
    controller.close();
  } }), { headers: { 'Content-Type': 'text/event-stream' } });
  await expect(consumeConversationStream(response, { conversationId: cid, turnId: tid, signal: new AbortController().signal, onParagraph: () => undefined, validateComplete: () => false })).rejects.toMatchObject({ kind: 'contract' });
});

test('split UTF-8/SSE bytes preserve paragraph text and abort closes an outstanding read', async () => {
  const controller = new AbortController();
  const receive = vi.fn(() => { controller.abort(); });
  let closed = false;
  const response = new Response(new ReadableStream({ start(stream) { for (const byte of wire(event)) stream.enqueue(new Uint8Array([byte])); }, cancel() { closed = true; } }), { headers: { 'Content-Type': 'text/event-stream' } });
  await expect(consumeConversationStream(response, { conversationId: cid, turnId: tid, signal: controller.signal, onParagraph: receive, validateComplete: () => false })).rejects.toBeDefined();
  expect(receive).toHaveBeenCalledWith(paragraph);
  expect(closed).toBe(true);
});

const conversation = {
  id: cid, title: '测试问题', revision: 2, createdAt: '2026-10-13T07:00:00Z', updatedAt: '2026-10-13T07:00:00Z',
  turns: [{ id: tid, sequence: 1, question: '测试问题', assistantName: '岑宁', assistantRevision: 0, skillId: null, answerUnavailable: false, contextTruncated: false, createdAt: '2026-10-13T07:00:00Z',
    answer: { status: 'answered', retrievalMode: 'hybrid', paragraphs: [paragraph], citations: [{ id: 'S1', resourceId: cid, resourceVersionId: cid, chunkId: tid, title: '交付说明', mediaType: 'text/plain', excerpt: '第一段。', locator: { type: 'text', headingPath: [], lineStart: 1, lineEnd: 1 }, score: 1 }] },
  }],
};

test.each([false, true])('complete must exactly agree with preview (mismatch=%s)', async mismatch => {
  vi.spyOn(console, 'error').mockImplementation(() => undefined);
  const value = structuredClone(conversation);
  if (mismatch) value.turns[0]!.answer.paragraphs[0]!.text = '被替换的段落';
  const response = new Response(new ReadableStream({ start(controller) { controller.enqueue(wire(event)); controller.enqueue(wire({ type: 'complete', conversationId: cid, turnId: tid, conversation: value })); controller.close(); } }), { headers: { 'Content-Type': 'text/event-stream' } });
  const result = consumeConversationStream(response, { conversationId: cid, turnId: tid, signal: new AbortController().signal, onParagraph: () => undefined, validateComplete: () => true });
  if (mismatch) await expect(result).rejects.toMatchObject({ kind: 'contract' });
  else await expect(result).resolves.toEqual(conversation);
});
