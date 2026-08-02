// 纯函数层的单元测试。这一层不碰 DOM、不碰网络，所以测试不需要浏览器、不需要 mock，
// 直接 import 就能跑 —— 这也是「把转换逻辑从 UI 里抽出来」换来的最直接好处。
//
// 测试选点的原则：只测契约（外部承诺的行为），不测实现细节。
// 所以断言的是「脏数据进来会变成什么形状」，而不是内部用了 filter 还是 for 循环。
//
// Day 7：normalizeDocuments 已退休，校验搬进了 Zod 层。它那批「脏数据 → 什么形状」
// 的行为测试整体移到 schema-parity.test.mjs（在真正的校验层上跑）。这里只留仍然
// 活在纯函数层的三个函数：filterByStatus、countByStatus、statusLabel。

import test from 'node:test';
import assert from 'node:assert/strict';
import {
  DOCUMENT_STATUSES,
  countByStatus,
  filterByStatus,
  statusLabel,
} from '../../src/lib/documents.ts';

const uuid = (suffix) => `00000000-0000-4000-8000-${String(suffix).padStart(12, '0')}`;

const sample = [
  { id: uuid(1), title: 'A', status: 'completed' },
  { id: uuid(2), title: 'B', status: 'processing' },
  { id: uuid(3), title: 'C', status: 'completed' },
  { id: uuid(4), title: 'D', status: 'unknown' },
];

test('filterByStatus returns everything for the "all" sentinel', () => {
  assert.deepEqual(filterByStatus(sample, 'all'), sample);
});

test('filterByStatus selects only the requested status', () => {
  assert.deepEqual(
    filterByStatus(sample, 'completed').map(({ id }) => id),
    [uuid(1), uuid(3)],
  );
  assert.deepEqual(
    filterByStatus(sample, 'unknown').map(({ id }) => id),
    [uuid(4)],
  );
});

test('filterByStatus returns empty for a status nobody has', () => {
  assert.deepEqual(filterByStatus(sample, 'failed'), []);
});

test('filterByStatus preserves the incoming order', () => {
  const ordered = filterByStatus(sample, 'completed');
  assert.deepEqual(ordered.map(({ id }) => id), [uuid(1), uuid(3)]);
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
  // 累加结果变成字符串拼接。正常路径上 status 已被校验层收敛过，
  // 这里守的是有人绕过它直接调用的情况。
  const counts = countByStatus([
    { id: uuid(1), title: 'A', status: 'toString' },
    { id: uuid(2), title: 'B', status: 'constructor' },
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
