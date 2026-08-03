import { spawn } from "node:child_process";
import { createServer } from "node:net";

const POLL_INTERVAL_MS = 200;
const FORCE_KILL_AFTER_MS = 5000;
const CLEANUP_DEADLINE_MS = 10000;

function hasExited(child) {
  return child.exitCode !== null || child.signalCode !== null;
}

export function assertPortAvailable(port, host = "127.0.0.1") {
  return new Promise((resolve, reject) => {
    const probe = createServer();

    probe.once("error", (error) => {
      if (error?.code === "EADDRINUSE") {
        reject(new Error(`Port ${port} is already in use`));
        return;
      }
      reject(error);
    });
    probe.once("listening", () => {
      probe.close((error) => {
        if (error) reject(error);
        else resolve();
      });
    });
    probe.listen({ host, port, exclusive: true });
  });
}

export async function settleCleanupTasks(tasks) {
  const results = await Promise.allSettled(
    tasks.map(({ run }) => Promise.resolve().then(run)),
  );
  return results.flatMap((result, index) =>
    result.status === "rejected"
      ? [{ name: tasks[index].name, reason: result.reason }]
      : [],
  );
}

function requireProcessId(child) {
  const pid = child.pid;
  if (!Number.isInteger(pid) || pid <= 0) {
    throw new Error(`Cannot manage child process with invalid pid: ${String(pid)}`);
  }
  return pid;
}

export function waitForChildSpawn(child) {
  if (child.pid !== undefined) return Promise.resolve();
  return new Promise((resolve, reject) => {
    child.once("spawn", resolve);
    child.once("error", reject);
  });
}

export async function waitForServer(url, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const remaining = deadline - Date.now();
    try {
      const response = await fetch(url, {
        signal: AbortSignal.timeout(Math.max(1, Math.min(POLL_INTERVAL_MS, remaining))),
      });
      if (response.ok) return;
    } catch {
      // The managed server is still starting or this attempt reached its deadline.
    }
    const delayMs = Math.min(POLL_INTERVAL_MS, Math.max(0, deadline - Date.now()));
    if (delayMs > 0) await new Promise((resolve) => setTimeout(resolve, delayMs));
  }
  throw new Error(`Server did not become ready within ${timeoutMs}ms: ${url}`);
}

function signalDirectChild(child, signal) {
  try {
    child.kill(signal);
  } catch (error) {
    if (error?.code !== "ESRCH") throw error;
  }
}

function signalPosixProcessTree(child, pid, signal) {
  try {
    process.kill(-pid, signal);
  } catch (error) {
    if (error?.code !== "ESRCH") throw error;
    signalDirectChild(child, signal);
  }
}

async function waitForExitOrKill(child, pid) {
  if (hasExited(child)) return;

  await new Promise((resolve, reject) => {
    let forceKillTimer;
    let deadlineTimer;
    let settled = false;

    const cleanup = () => {
      if (forceKillTimer !== undefined) clearTimeout(forceKillTimer);
      if (deadlineTimer !== undefined) clearTimeout(deadlineTimer);
      child.removeListener("exit", finish);
      child.removeListener("close", finish);
    };
    const finish = () => {
      if (settled) return;
      settled = true;
      cleanup();
      resolve();
    };
    const fail = (error) => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(error);
    };

    child.once("exit", finish);
    child.once("close", finish);
    if (hasExited(child)) {
      finish();
      return;
    }

    forceKillTimer = setTimeout(() => {
      try {
        if (process.platform === "win32") signalDirectChild(child, "SIGKILL");
        else signalPosixProcessTree(child, pid, "SIGKILL");
      } catch (error) {
        fail(error);
      }
    }, FORCE_KILL_AFTER_MS);
    deadlineTimer = setTimeout(() => {
      fail(new Error(`Process ${pid} did not exit within ${CLEANUP_DEADLINE_MS}ms`));
    }, CLEANUP_DEADLINE_MS);
  });
}

export async function stopProcessTree(child) {
  if (child === null || child.pid === undefined || hasExited(child)) return;
  const pid = requireProcessId(child);

  if (process.platform === "win32") {
    await new Promise((resolve) => {
      const killer = spawn("taskkill", ["/pid", String(pid), "/t", "/f"], {
        stdio: "ignore",
      });
      killer.once("close", resolve);
      killer.once("error", resolve);
    });
    if (!hasExited(child)) signalDirectChild(child, "SIGKILL");
  } else {
    signalPosixProcessTree(child, pid, "SIGTERM");
  }

  await waitForExitOrKill(child, pid);
}
