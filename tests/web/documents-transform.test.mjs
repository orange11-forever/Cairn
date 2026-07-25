// 纯函数层的单元测试。这一层不碰 DOM、不碰网络，所以测试不需要浏览器、不需要 mock，
// 直接 import 就能跑 —— 这也是「把转换逻辑从 UI 里抽出来」换来的最直接好处。
//
// 测试选点的原则：只测契约（外部承诺的行为），不测实现细节。
// 所以断言的是「脏数据进来会变成什么形状」，而不是内部用了 filter 还是 for 循环。

import test from 'node:test';
import assert from 'node:assert/strict';
import {
  DOCUMENT_STATUSES,
  countByStatus,
  filterByStatus,
  normalizeDocuments,
  statusLabel,
} from '../../apps/web/src/lib/documents.js';

test('normalizeDocuments keeps well-formed documents untouched', () => {
  const result = normalizeDocuments([
    { id: 1, title: '季度复盘.md', status: 'completed' },
    { id: 'abc', title: '架构评审记录', status: 'processing' },
  ]);

  assert.deepEqual(result, [
    { id: 1, title: '季度复盘.md', status: 'completed' },
    { id: 'abc', title: '架构评审记录', status: 'processing' },
  ]);
});

test('normalizeDocuments throws when the response is not an array', () => {
  // 契约整个坏了。静默返回 [] 会把「后端故障」显示成「你还没有文档」，是最坏的谎报，
  // 所以这里必须抛错而不是降级。
  for (const bad of [null, undefined, {}, '[]', 42, { items: [] }]) {
    assert.throws(() => normalizeDocuments(bad), TypeError);
  }
});

test('normalizeDocuments drops entries without a usable id', () => {
  const result = normalizeDocuments([
    { id: 1, title: '有 id', status: 'completed' },
    { title: '没有 id', status: 'completed' },
    { id: null, title: 'id 是 null', status: 'completed' },
    { id: undefined, title: 'id 是 undefined', status: 'completed' },
    null,
    undefined,
  ]);

  assert.equal(result.length, 1);
  assert.equal(result[0].id, 1);
});

test('normalizeDocuments keeps id 0 and empty-string id', () => {
  // 回归测试：用 `!item.id` 判断会把合法的 0 和 '' 一起丢掉，这是最容易写错的一处。
  const result = normalizeDocuments([
    { id: 0, title: '第零号文档', status: 'completed' },
    { id: '', title: '空串 id', status: 'completed' },
  ]);

  assert.deepEqual(result.map(({ id }) => id), [0, '']);
});

test('normalizeDocuments substitutes a placeholder for a missing title', () => {
  const result = normalizeDocuments([
    { id: 1, status: 'completed' },
    { id: 2, title: '', status: 'completed' },
    { id: 3, title: '   ', status: 'completed' },
    { id: 4, title: 42, status: 'completed' },
  ]);

  assert.deepEqual(
    result.map(({ title }) => title),
    ['未命名文档', '未命名文档', '未命名文档', '未命名文档'],
  );
});

test('normalizeDocuments trims surrounding whitespace from titles', () => {
  const [doc] = normalizeDocuments([
    { id: 1, title: '  设计评审.pdf \n', status: 'completed' },
  ]);

  assert.equal(doc.title, '设计评审.pdf');
});

test('normalizeDocuments downgrades unrecognized statuses to unknown', () => {
  // 后端加新状态（Day 21 的 pending/running）时前端应降级显示，不能让文档凭空消失。
  const result = normalizeDocuments([
    { id: 1, title: 'A', status: 'pending' },
    { id: 2, title: 'B' },
    { id: 3, title: 'C', status: null },
    { id: 4, title: 'D', status: 'COMPLETED' },
  ]);

  assert.equal(result.length, 4);
  assert.deepEqual(
    result.map(({ status }) => status),
    ['unknown', 'unknown', 'unknown', 'unknown'],
  );
});

test('normalizeDocuments does not mutate or alias its input', () => {
  const raw = [{ id: 1, title: 'A', status: 'completed', extra: 'keep me' }];
  const result = normalizeDocuments(raw);

  assert.deepEqual(raw, [
    { id: 1, title: 'A', status: 'completed', extra: 'keep me' },
  ]);
  assert.notEqual(result[0], raw[0]);
  // 只保留已知字段，后端多塞的字段不该漏进 UI 层
  assert.deepEqual(Object.keys(result[0]).sort(), ['id', 'status', 'title']);
});

test('normalizeDocuments returns an empty array for an empty response', () => {
  assert.deepEqual(normalizeDocuments([]), []);
});

const sample = [
  { id: 1, title: 'A', status: 'completed' },
  { id: 2, title: 'B', status: 'processing' },
  { id: 3, title: 'C', status: 'completed' },
  { id: 4, title: 'D', status: 'unknown' },
];

test('filterByStatus returns everything for the "all" sentinel', () => {
  assert.deepEqual(filterByStatus(sample, 'all'), sample);
});

test('filterByStatus selects only the requested status', () => {
  assert.deepEqual(
    filterByStatus(sample, 'completed').map(({ id }) => id),
    [1, 3],
  );
  assert.deepEqual(
    filterByStatus(sample, 'unknown').map(({ id }) => id),
    [4],
  );
});

test('filterByStatus returns empty for a status nobody has', () => {
  assert.deepEqual(filterByStatus(sample, 'failed'), []);
});

test('filterByStatus preserves the incoming order', () => {
  const ordered = filterByStatus(sample, 'completed');
  assert.deepEqual(ordered.map(({ id }) => id), [1, 3]);
});

test('countByStatus reports zero for known statuses nobody has', () => {
  // UI 的角标不该自己补 0，所以三个已知状态必须始终出现在结果里。
  const counts = countByStatus([]);

  for (const status of DOCUMENT_STATUSES) {
    assert.equal(counts[status], 0, `missing zero entry for ${status}`);
  }
});

test('countByStatus tallies known and unknown statuses together', () => {
  // 展开成普通对象再比：计数表刻意用了 null 原型，deepEqual 在 strict 模式下会比较原型。
  assert.deepEqual({ ...countByStatus(sample) }, {
    completed: 2,
    processing: 1,
    failed: 0,
    unknown: 1,
  });
});

test('countByStatus is immune to prototype-shaped status names', () => {
  // 若计数表带 Object.prototype，counts["toString"] 会拿到继承的函数，`?? 0` 失效，
  // 累加结果变成字符串拼接。正常路径上 status 已被 normalizeDocuments 收敛过，
  // 这里守的是有人绕过它直接调用的情况。
  const counts = countByStatus([
    { id: 1, title: 'A', status: 'toString' },
    { id: 2, title: 'B', status: 'constructor' },
  ]);

  assert.equal(counts.toString, 1);
  assert.equal(counts.constructor, 1);
  for (const value of Object.values(counts)) {
    assert.equal(typeof value, 'number');
  }
});

test('countByStatus totals match the input length', () => {
  const counts = countByStatus(sample);
  const total = Object.values(counts).reduce((sum, n) => sum + n, 0);

  assert.equal(total, sample.length);
});

test('statusLabel maps every known status to a distinct Chinese label', () => {
  const labels = DOCUMENT_STATUSES.map((status) => statusLabel(status));

  assert.equal(new Set(labels).size, labels.length);
  for (const label of labels) {
    assert.ok(label.length > 0);
    assert.notEqual(label, undefined);
  }
});

test('statusLabel falls back to the unknown label for anything unexpected', () => {
  const fallback = statusLabel('unknown');

  for (const weird of ['pending', '', null, undefined, 0, 'toString']) {
    assert.equal(statusLabel(weird), fallback);
  }
});
