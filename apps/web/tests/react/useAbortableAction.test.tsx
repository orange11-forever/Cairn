import { act, renderHook, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { useAbortableAction } from "../../src/hooks/useAbortableAction.ts";

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

test("an older aborted run cannot replace the newer pending state", async () => {
  const first = deferred<string>();
  const second = deferred<string>();
  const fn = vi.fn((_value: string, signal: AbortSignal) => {
    const current = fn.mock.calls.length === 1 ? first : second;
    signal.addEventListener("abort", () =>
      current.reject(new DOMException("aborted", "AbortError")),
    );
    return current.promise;
  });
  const { result } = renderHook(() => useAbortableAction(fn));

  let firstRun: Promise<string | undefined> | undefined;
  let secondRun: Promise<string | undefined> | undefined;
  act(() => {
    firstRun = result.current.run("first");
  });
  act(() => {
    secondRun = result.current.run("second");
  });

  await waitFor(() => expect(result.current.state.phase).toBe("pending"));
  second.resolve("new");
  await expect(secondRun).resolves.toBe("new");
  await expect(firstRun).resolves.toBeUndefined();
  await waitFor(() => expect(result.current.state.phase).toBe("idle"));
});

test("cancel followed by a signal-ignoring success cannot leave pending", async () => {
  const request = deferred<string>();
  const { result } = renderHook(() => useAbortableAction(() => request.promise));

  let run: Promise<string | undefined> | undefined;
  act(() => {
    run = result.current.run();
  });
  act(() => result.current.cancel());
  expect(result.current.state.phase).toBe("idle");
  request.resolve("ignored");

  await expect(run).resolves.toBeUndefined();
  await waitFor(() => expect(result.current.state.phase).toBe("idle"));
});

test("the parent session signal cancels the active command", async () => {
  const parent = new AbortController();
  const request = deferred<string>();
  const { result } = renderHook(() =>
    useAbortableAction(() => request.promise, parent.signal),
  );
  act(() => {
    void result.current.run();
  });
  act(() => parent.abort());
  expect(result.current.state.phase).toBe("idle");
  request.resolve("ignored");
  await waitFor(() => expect(result.current.state.phase).toBe("idle"));
});

test("unmount aborts the active command and ignores its eventual result", async () => {
  const request = deferred<string>();
  let signal: AbortSignal | undefined;
  const { result, unmount } = renderHook(() =>
    useAbortableAction((_signal: AbortSignal) => {
      signal = _signal;
      return request.promise;
    }),
  );

  let run: Promise<string | undefined> | undefined;
  act(() => {
    run = result.current.run();
  });
  unmount();
  expect(signal?.aborted).toBe(true);
  request.resolve("ignored");
  await expect(run).resolves.toBeUndefined();
});
