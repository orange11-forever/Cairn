// 校验层回归护栏。
//
// 这个文件的前身是「迁移安全网」：Day 7 用 Zod 重写校验层时，把新层和 Day 5 手写的
// normalizeDocuments 并排喂同一批脏数据逐条比对，防止「重写时悄悄放宽了当年抓 bug 的那一条」。
//
// 那次比对已经用一个**独立预言机**跑过并全绿（拿 git 里没被改过的 Day 5 老实现当裁判，
// 逐字确认数据处置一致，唯一的差异是非数组从 throw TypeError 改成 throw ApiError("contract")，
// 那是刻意的行为变更不是放宽）。等价既已证明，老实现就退休了，调用方全部切到 Zod 层。
//
// 于是这个文件的角色变了：不再比对两套实现，而是**把 Day 5/6 那些用真 bug 换来的行为
// 逐条钉在新 schema 上**。将来有人改 schema 时若把某个老坑重新挖开（把合法的 id=0 判成假、
// 把脏数据静默转成合法值、让未知状态把文档整条吞掉），这里就会红。
//
// 每条测试的输入都对应一个踩过的坑，注释说明它守的是什么。

import test from 'node:test';
import assert from 'node:assert/strict';

import { DocumentSchema } from '../../apps/web/src/schemas/documents.ts';
import { parseList } from '../../apps/web/src/schemas/parse.ts';
import { ApiError } from '../../apps/web/src/api/errors.ts';

/** 用校验层跑一遍，只取 items，便于直接和期望值比。 */
const viaSchema = (raw) => parseList(DocumentSchema, raw, 'TEST').items;

// parseList 在丢数据时会 console.warn，测试里会刷屏。
// 静音但**记录调用次数**——次数本身是要断言的东西（丢了数据必须有信号）。
function silenceWarnings(fn) {
  const original = console.warn;
  const calls = [];
  console.warn = (...args) => calls.push(args.join(' '));
  try {
    return { result: fn(), warnings: calls };
  } finally {
    console.warn = original;
  }
}

function silenceErrors(fn) {
  const original = console.error;
  console.error = () => {};
  try {
    return fn();
  } finally {
    console.error = original;
  }
}

// ---- 逐条钉住 Day 5/6 的行为 ----

test('合规数据原样通过', () => {
  const raw = [
    { id: 1, title: '季度复盘.md', status: 'completed' },
    { id: 'abc', title: '架构评审记录', status: 'processing' },
  ];
  const expected = [
    { id: 1, title: '季度复盘.md', status: 'completed' },
    { id: 'abc', title: '架构评审记录', status: 'processing' },
  ];

  assert.deepEqual(viaSchema(raw), expected);
});

test('整体不是数组 —— 拒绝并抛 ApiError("contract")', () => {
  for (const bad of [null, undefined, {}, '[]', 42, { items: [] }]) {
    // 这里抛 ApiError("contract") 而不是老实现的 TypeError，是**刻意的行为变更**，不是放宽：
    // TypeError 到了 UI 层没人认识，只能显示"未知错误"；
    // ApiError 带 kind，UI 能据此显示"数据格式不正确"并且**不显示重试按钮**
    //（contract 错误重试永远是同样结果）。拒绝这件事本身一条没少。
    const error = silenceErrors(() => {
      try {
        viaSchema(bad);
        return null;
      } catch (e) {
        return e;
      }
    });
    assert.ok(error instanceof ApiError, `${JSON.stringify(bad)} 应抛 ApiError`);
    assert.equal(error.kind, 'contract');
    assert.equal(error.retryable, false, 'contract 错误不该建议用户重试');
  }
});

test('丢弃没有可用 id 的条目', () => {
  const raw = [
    { id: 1, title: '有 id', status: 'completed' },
    { title: '没有 id', status: 'completed' },
    { id: null, title: 'id 是 null', status: 'completed' },
    { id: undefined, title: 'id 是 undefined', status: 'completed' },
    null,
    undefined,
  ];

  const { result, warnings } = silenceWarnings(() => parseList(DocumentSchema, raw, 'TEST'));
  assert.equal(result.items.length, 1);
  assert.equal(result.items[0].id, 1);
  // 丢了 5 条就必须报 5 条，静默丢数据是不可接受的
  assert.equal(result.dropped, 5);
  assert.equal(warnings.length, 1, '丢弃数据必须留下一条可见的信号');
  assert.match(warnings[0], /5\/6/);
});

test('保留 id 为 0 和空字符串的条目（Day 5 回归点）', () => {
  // 用 `!item.id` 判断会把合法的 0 和 '' 一起丢掉，这是最容易写错的一处。
  const raw = [
    { id: 0, title: '第零号文档', status: 'completed' },
    { id: '', title: '空串 id', status: 'completed' },
  ];

  assert.deepEqual(viaSchema(raw).map(({ id }) => id), [0, '']);
});

test('标题缺失/空白/非字符串都换成占位符', () => {
  const raw = [
    { id: 1, status: 'completed' },
    { id: 2, title: '', status: 'completed' },
    { id: 3, title: '   ', status: 'completed' },
    { id: 4, title: 42, status: 'completed' },
  ];
  const expected = ['未命名文档', '未命名文档', '未命名文档', '未命名文档'];

  assert.deepEqual(viaSchema(raw).map(({ title }) => title), expected);
});

test('标题两端空白被裁掉', () => {
  const raw = [{ id: 1, title: '  设计评审.pdf \n', status: 'completed' }];

  assert.equal(viaSchema(raw)[0].title, '设计评审.pdf');
});

test('不认识的状态降级成 unknown，文档不消失', () => {
  // 后端加新状态（Day 21 的 pending/running）时前端应降级显示，不能让文档凭空消失。
  const raw = [
    { id: 1, title: 'A', status: 'pending' },
    { id: 2, title: 'B' },
    { id: 3, title: 'C', status: null },
    { id: 4, title: 'D', status: 'COMPLETED' },
  ];
  const expected = ['unknown', 'unknown', 'unknown', 'unknown'];

  const viaNew = viaSchema(raw);
  assert.equal(viaNew.length, 4, '降级不是丢弃：四条都要留下');
  assert.deepEqual(viaNew.map(({ status }) => status), expected);
});

test('不改动入参，且剥掉未声明的字段', () => {
  const raw = [{ id: 1, title: 'A', status: 'completed', extra: 'keep me' }];

  const input = structuredClone(raw);
  const result = viaSchema(input);

  assert.deepEqual(input, raw, '入参不可被修改');
  assert.notEqual(result[0], input[0], '不可与入参共享引用');
  // 后端多塞的字段不该漏进 UI 层
  assert.deepEqual(Object.keys(result[0]).sort(), ['id', 'status', 'title']);
});

test('空数组返回空数组，且不算错误', () => {
  const empty = parseList(DocumentSchema, [], 'TEST');
  assert.deepEqual(empty.items, []);
  assert.equal(empty.dropped, 0, '空列表是正常的（新用户），不是丢了数据');
});

test('混合脏数据 —— 好的留下、坏的丢掉、可降级的降级', () => {
  // 这条是前面各条的组合，模拟真实的脏响应：三种处置同时发生。
  const raw = [
    { id: 1, title: '正常', status: 'completed' },
    { id: 2, title: '', status: 'pending' },   // 标题占位 + 状态降级，留下
    { title: '无 id', status: 'completed' },   // 丢弃
    'not an object',                            // 丢弃
    { id: 3, title: '  裁空白  ', status: 'failed' },
  ];

  const { result } = silenceWarnings(() => parseList(DocumentSchema, raw, 'TEST'));

  assert.deepEqual(result.items, [
    { id: 1, title: '正常', status: 'completed' },
    { id: 2, title: '未命名文档', status: 'unknown' },
    { id: 3, title: '裁空白', status: 'failed' },
  ]);
  assert.equal(result.dropped, 2);
});
