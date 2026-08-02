import { spawn } from "node:child_process";

function hasExited(child) {
  return child.exitCode !== null || child.signalCode !== null;
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
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // The managed server is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(`Server did not become ready within ${timeoutMs}ms: ${url}`);
}

async function waitForExitOrKill(child, pid) {
  if (hasExited(child)) return;

  await new Promise((resolve, reject) => {
    let timer;
    let settled = false;

    const cleanup = () => {
      if (timer !== undefined) clearTimeout(timer);
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

    timer = setTimeout(() => {
      if (process.platform === "win32") return;
      try {
        process.kill(-pid, "SIGKILL");
      } catch (error) {
        if (error?.code !== "ESRCH") fail(error);
        else if (hasExited(child)) finish();
      }
    }, 5000);
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
  } else {
    try {
      process.kill(-pid, "SIGTERM");
    } catch (error) {
      if (error?.code !== "ESRCH") throw error;
    }
  }

  await waitForExitOrKill(child, pid);
}
