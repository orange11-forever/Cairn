// Day 4 Mock 后端
// 用 Node 自带的 http 模块起一个真实的 HTTP 服务，供浏览器用真 fetch 调用。
// 通过 ?scenario= 切换不同响应，制造出六种前端状态需要应对的真实情况。
//
// 运行：node mocks/docs-server.mjs
// 然后浏览器访问 http://localhost:8787/api/docs?scenario=success
//
// Day 9 加了三个 POST 端点：/api/login、/api/ask、/api/uploads。
//
// 为什么不用 setTimeout 在前端伪造成功/失败，非要让 mock 真的回一个 401：
// 表单最难教的部分是**两类错误的区别**——
//   字段校验错误：前端自己就知道（邮箱没有 @），显示在字段旁边
//   服务端错误：只有问过后端才知道（密码不对），显示在表单级别
// 假请求永远只有第二类的"样子"没有它的"来源"，于是"错误该显示在哪"这个问题
// 就变成了凭感觉。有真 401 之后，答案是从数据流里读出来的。

import { createServer } from "node:http";

const PORT = 8787;

const IDS = Object.freeze({
  user: "00000000-0000-4000-8000-000000001001",
  document1: "00000000-0000-4000-8000-000000000001",
  document2: "00000000-0000-4000-8000-000000000002",
  document3: "00000000-0000-4000-8000-000000000003",
  document4: "00000000-0000-4000-8000-000000000004",
});

// 模拟数据库里的文档
const DOCS = [
  { id: IDS.document1, title: "产品需求文档", status: "completed" },
  { id: IDS.document2, title: "API 接口设计", status: "processing" },
  { id: IDS.document3, title: "测试报告 v2", status: "completed" },
  { id: IDS.document4, title: "部署手册", status: "failed" },
];

// Day 9：登录用的假账号。密码明文放在这里是因为它是 mock——
// 真后端的密码哈希是 Day 18 的题目，那天要讲为什么明文存储不可接受。
const DEMO_USER = {
  email: "demo@cairn.dev",
  password: "cairn-demo-2026",
  user: { id: IDS.user, email: "demo@cairn.dev", displayName: "演示用户", role: "member" },
};

// Day 9：上传的服务端约束。**故意和前端 lib/validation.ts 里的一样。**
//
// 这不是重复劳动，是两个不同职责恰好用了同一个数字：
//   前端校验 = 体验。别让用户等一次往返才知道选错了文件。
//   后端校验 = 边界。它是真正说不的那个——前端校验能被绕过（改 JS、直接 curl），
//              而"文件不能超过 10MB"如果只有前端管，那就等于没管。
// Day 19 做真上传接口时这两个数字会挪到共享配置里，但**校验本身仍然要写两遍**。
const SERVER_MAX_FILE_BYTES = 10 * 1024 * 1024;
const SERVER_ALLOWED_EXTENSIONS = [".pdf", ".md", ".txt", ".docx"];

// 小工具：延迟 ms 毫秒（用 Promise 包一层 setTimeout）
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** 读完整个请求体并解析 JSON。body 不是 JSON 时返回 null，由调用方决定怎么办。 */
async function readJsonBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const raw = Buffer.concat(chunks).toString("utf8");
  if (raw === "") return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function writeError(req, res, status, code, message) {
  const incoming = req.headers["x-request-id"];
  const traceId = typeof incoming === "string" && incoming !== "" ? incoming : crypto.randomUUID();
  res.setHeader("X-Request-ID", traceId);
  res.writeHead(status);
  res.end(JSON.stringify({ message, code, traceId }));
}

const server = createServer(async (req, res) => {
  // 浏览器从 file:// 或别的端口打过来会触发跨域，这里放行（Day 16 会正经讲 CORS）
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Content-Type", "application/json; charset=utf-8");

  const url = new URL(req.url, `http://localhost:${PORT}`);

  // Day 9：CORS 预检。
  //
  // 带 Content-Type: application/json 的跨域请求不是"简单请求"，浏览器会先发一次
  // OPTIONS 问"我能这么发吗"。不答这一问，POST 根本不会发出去——
  // 而浏览器控制台报的是 CORS 错误，很容易误以为是 Allow-Origin 没设对。
  if (req.method === "OPTIONS") {
    res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
    res.setHeader("Access-Control-Allow-Headers", "Content-Type, X-Request-ID");
    res.setHeader("Access-Control-Max-Age", "86400");
    res.writeHead(204);
    res.end();
    return;
  }

  if (url.pathname === "/health" && req.method === "GET") {
    res.writeHead(204);
    res.end();
    return;
  }

  // ---- POST /api/v1/login ----
  if (url.pathname === "/api/v1/login" && req.method === "POST") {
    const body = await readJsonBody(req);
    // 延迟 700ms：不为好看，是为了让"提交中"这个状态真的存在足够长的时间，
    // 好让 Playwright 能断言按钮变成禁用、文案变成"登录中…"。
    // 零延迟的 mock 会让提交中这一帧根本抓不到，于是那段代码从来没被验证过。
    await delay(700);

    if (body === null || typeof body.email !== "string" || typeof body.password !== "string") {
      writeError(req, res, 400, "validation_error", "请求体必须包含 email 和 password");
      return;
    }

    console.log(`[mock] POST /api/v1/login email=${body.email}`);

    if (body.email.trim().toLowerCase() !== DEMO_USER.email || body.password !== DEMO_USER.password) {
      // 401 + 一句**不区分**"邮箱不存在"和"密码错误"的文案。
      // 区分开会变成账号枚举漏洞：攻击者能靠错误文案批量确认哪些邮箱注册过。
      // Day 13/18 讲鉴权时会重提这条。
      writeError(req, res, 401, "invalid_credentials", "邮箱或密码不正确");
      return;
    }

    res.writeHead(200);
    res.end(JSON.stringify({ user: DEMO_USER.user }));
    return;
  }

  // ---- POST /api/v1/ask ----
  if (url.pathname === "/api/v1/ask" && req.method === "POST") {
    const body = await readJsonBody(req);

    if (body === null || typeof body.question !== "string" || body.question.trim() === "") {
      writeError(req, res, 400, "validation_error", "question 不能为空");
      return;
    }

    console.log(`[mock] POST /api/v1/ask question=${body.question.slice(0, 30)}`);

    // 1500ms：比 login 长，因为这一条要留出「用户点停止生成」的窗口。
    // 仍然小于客户端 3000ms 的超时，所以不打断它就会正常成功。
    //
    // 关键点：这里没有任何"取消"的处理代码。服务端照样跑完 1500ms 并试图响应，
    // 是**客户端** abort 之后不再读那个响应。这正是 AbortController 的真实语义——
    // 它取消的是浏览器这一侧的等待，不是让服务器停下来。
    await delay(1500);

    res.writeHead(200);
    res.end(
      JSON.stringify({
        kind: "grounded_answer",
        id: crypto.randomUUID(),
        content: "严重故障需要先通知当班负责人，再按照升级矩阵联系服务负责人。",
        createdAt: new Date().toISOString(),
        citations: [
          {
            documentId: IDS.document1,
            documentTitle: "值班流程",
            snippet: "P0 故障 5 分钟内通知当班负责人，15 分钟内拉起服务负责人。",
            anchor: "section-4",
            score: 0.92,
          },
        ],
      }),
    );
    return;
  }

  // ---- POST /api/v1/uploads ----
  if (url.pathname === "/api/v1/uploads" && req.method === "POST") {
    const body = await readJsonBody(req);
    await delay(600);

    if (body === null || !Array.isArray(body.files) || body.files.length === 0) {
      writeError(req, res, 400, "validation_error", "files 必须是非空数组");
      return;
    }

    console.log(`[mock] POST /api/v1/uploads files=${body.files.length}`);

    // 服务端**重新**校验一遍。见文件头 SERVER_MAX_FILE_BYTES 的注释。
    for (const file of body.files) {
      if (typeof file?.name !== "string" || typeof file?.size !== "number") {
        writeError(req, res, 400, "validation_error", "每个文件必须有 name 和 size");
        return;
      }

      const dot = file.name.lastIndexOf(".");
      const ext = dot > 0 ? file.name.slice(dot).toLowerCase() : "";
      if (!SERVER_ALLOWED_EXTENSIONS.includes(ext)) {
        writeError(
          req,
          res,
          415,
          "unsupported_media_type",
          `服务端不接受 ${ext || "无扩展名"} 类型的文件`,
        );
        return;
      }

      if (file.size > SERVER_MAX_FILE_BYTES) {
        writeError(req, res, 413, "payload_too_large", `${file.name} 超过服务端 10MB 上限`);
        return;
      }
    }

    res.writeHead(201); // 201 Created：创建了处理任务，不是 200
    res.end(
      JSON.stringify({
        accepted: body.files.length,
        // 上传只创建"待处理"的任务，不返回已就绪的文档——解析和索引是异步的
        // （Day 21 的 worker 干这个活）。这个形状现在就定下来，
        // 好让前端从今天起就知道"上传成功 ≠ 可以问答了"。
        jobs: body.files.map((file) => ({
          id: crypto.randomUUID(),
          documentTitle: file.name,
          status: "pending",
        })),
      }),
    );
    return;
  }

  if (url.pathname !== "/api/v1/documents") {
    writeError(req, res, 404, "not_found", "Not Found");
    return;
  }

  const scenario = url.searchParams.get("scenario") ?? "success";
  console.log(`[mock] GET /api/v1/documents?scenario=${scenario}`);

  switch (scenario) {
    // 正常：延迟 600ms 后返回完整数据
    case "success": {
      await delay(600);
      res.writeHead(200);
      res.end(JSON.stringify(DOCS));
      return;
    }

    // 空数据：请求成功，但一条都没有（新用户还没上传）——注意这不是错误
    case "empty": {
      await delay(600);
      res.writeHead(200);
      res.end(JSON.stringify([]));
      return;
    }

    // HTTP 错误：服务器 500。关键点——fetch 不会因此 reject，前端必须自己查 response.ok
    case "error": {
      await delay(600);
      writeError(req, res, 500, "internal_error", "服务器内部错误");
      return;
    }

    // 慢响应：拖 5 秒。客户端会用 AbortController 在 3 秒时主动放弃，触发超时
    case "slow": {
      await delay(5000);
      res.writeHead(200);
      res.end(JSON.stringify(DOCS));
      return;
    }

    default: {
      writeError(req, res, 400, "validation_error", `未知 scenario: ${scenario}`);
    }
  }
});

server.listen(PORT, () => {
  console.log(`Mock 后端已启动：http://localhost:${PORT}`);
  console.log(`试试：http://localhost:${PORT}/api/v1/documents?scenario=success`);
  console.log(`登录账号：${DEMO_USER.email} / ${DEMO_USER.password}`);
  console.log(`停止：Ctrl+C（停掉后前端 fetch 会真的抛网络错误，用来演示网络失败状态）`);
});
