import { useEffect, useRef, useState } from "react";
import type { Task } from "../../api/projects.ts";
import { Odometer } from "./Odometer.tsx";

type ProgressTask = Pick<Task, "id" | "status">;

export function ProgressCairn({ tasks, hasMore }: { tasks: readonly ProgressTask[]; hasMore: boolean }) {
  const previous = useRef(new Map(tasks.map(task => [task.id, task.status])));
  const [landing, setLanding] = useState<string | null>(null);
  const completed = tasks.filter(task => task.status === "done").length;
  const levels = Math.min(tasks.length, 6);
  const filled = tasks.length === 0 ? 0 : Math.ceil(completed / tasks.length * levels);

  useEffect(() => {
    const added = tasks.find(task => task.status === "done" && previous.current.has(task.id) && previous.current.get(task.id) !== "done");
    previous.current = new Map(tasks.map(task => [task.id, task.status]));
    if (added) setLanding(added.id);
    else if (landing && !tasks.some(task => task.id === landing && task.status === "done")) setLanding(null);
  }, [tasks, landing]);
  useEffect(() => {
    if (landing === null) return;
    const timer = window.setTimeout(() => setLanding(null), 700);
    return () => window.clearTimeout(timer);
  }, [landing]);

  return <div className="progress-cairn" data-adding={landing ? "true" : undefined}>
    <div className="progress-cairn-stack" aria-hidden="true">
      {Array.from({ length: Math.max(1, levels) }, (_, index) => <span
        className="stone"
        key={index === filled - 1 ? `${index}:${landing ?? "rest"}` : index}
        data-filled={index < filled ? "true" : undefined}
        data-cap={index === filled - 1 ? "true" : undefined}
        style={{ width: `${70 - index * 9}px` }}
      />)}
    </div>
    <div className="progress-cairn-copy" role="status" aria-label="任务完成进度" aria-atomic="true">
      <span>{hasMore ? "已加载任务" : "项目进度"}</span>
      <p>已完成 <Odometer value={completed} /> / <Odometer value={tasks.length} /> 项</p>
    </div>
  </div>;
}
