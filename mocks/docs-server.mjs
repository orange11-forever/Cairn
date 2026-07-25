// Day 4 Mock 后端
// 用 Node 自带的 http 模块起一个真实的 HTTP 服务，供浏览器用真 fetch 调用。
// 通过 ?scenario= 切换不同响应，制造出六种前端状态需要应对的真实情况。
//
// 运行：node practice/day4/mock-server.mjs
// 然后浏览器访问 http://localhost:8787/api/docs?scenario=success

import { createServer } from "node:http";

const PORT = 8787;

// 模拟数据库里的文档
const DOCS = [
  { id: 1, title: "产品需求文档", status: "completed" },
  { id: 2, title: "API 接口设计", status: "processing" },
  { id: 3, title: "测试报告 v2", status: "completed" },
  { id: 4, title: "部署手册", status: "failed" },
];

// 小工具：延迟 ms 毫秒（用 Promise 包一层 setTimeout）
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const server = createServer(async (req, res) => {
  // 浏览器从 file:// 或别的端口打过来会触发跨域，这里放行（Day 16 会正经讲 CORS）
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Content-Type", "application/json; charset=utf-8");

  const url = new URL(req.url, `http://localhost:${PORT}`);

  if (url.pathname !== "/api/docs") {
    res.writeHead(404);
    res.end(JSON.stringify({ message: "Not Found" }));
    return;
  }

  const scenario = url.searchParams.get("scenario") ?? "success";
  console.log(`[mock] GET /api/docs?scenario=${scenario}`);

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
      res.writeHead(500);
      res.end(JSON.stringify({ message: "服务器内部错误" }));
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
      res.writeHead(400);
      res.end(JSON.stringify({ message: `未知 scenario: ${scenario}` }));
    }
  }
});

server.listen(PORT, () => {
  console.log(`Mock 后端已启动：http://localhost:${PORT}`);
  console.log(`试试：http://localhost:${PORT}/api/docs?scenario=success`);
  console.log(`停止：Ctrl+C（停掉后前端 fetch 会真的抛网络错误，用来演示网络失败状态）`);
});
