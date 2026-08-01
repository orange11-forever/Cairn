import { runTask } from "./run-task.mjs";

const taskNames = process.argv.slice(2);

if (taskNames.length === 0) {
  console.error("Usage: node scripts/run-tasks.mjs <task> [task...]");
  process.exitCode = 2;
} else {
  for (const taskName of taskNames) {
    const exitCode = await runTask(taskName);
    if (exitCode !== 0) {
      process.exitCode = exitCode;
      break;
    }
  }
}
