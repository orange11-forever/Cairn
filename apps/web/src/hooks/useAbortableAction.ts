import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, toApiError } from "../api/errors.ts";

export type ActionState =
  | { phase: "idle" }
  | { phase: "pending" }
  | { phase: "error"; error: ApiError };

export interface AbortableAction<Args extends unknown[], Result> {
  state: ActionState;
  pending: boolean;
  run: (...args: Args) => Promise<Result | undefined>;
  cancel(): void;
  reset(): void;
}

interface InFlight {
  controller: AbortController;
  generation: number;
}

export function useAbortableAction<Args extends unknown[], Result>(
  fn: (...args: [...Args, AbortSignal]) => Promise<Result>,
  parentSignal?: AbortSignal,
): AbortableAction<Args, Result> {
  const [state, setState] = useState<ActionState>({ phase: "idle" });
  const fnRef = useRef(fn);
  const inFlight = useRef<InFlight | null>(null);
  const generation = useRef(0);
  const mounted = useRef(true);

  useEffect(() => {
    fnRef.current = fn;
  });

  function isCurrent(current: InFlight): boolean {
    return (
      mounted.current &&
      inFlight.current === current &&
      generation.current === current.generation
    );
  }

  const cancel = useCallback(() => {
    generation.current += 1;
    const current = inFlight.current;
    inFlight.current = null;
    current?.controller.abort();
    if (mounted.current) setState({ phase: "idle" });
  }, []);

  const run = useCallback(
    async (...args: Args): Promise<Result | undefined> => {
      if (parentSignal?.aborted === true) {
        if (mounted.current) setState({ phase: "idle" });
        return undefined;
      }

      inFlight.current?.controller.abort();

      const current: InFlight = {
        controller: new AbortController(),
        generation: generation.current + 1,
      };
      generation.current = current.generation;
      inFlight.current = current;
      setState({ phase: "pending" });

      const signal =
        parentSignal === undefined
          ? current.controller.signal
          : AbortSignal.any([current.controller.signal, parentSignal]);

      try {
        const result = await fnRef.current(...args, signal);
        if (signal.aborted || !isCurrent(current)) return undefined;
        setState({ phase: "idle" });
        return result;
      } catch (error) {
        if (!isCurrent(current)) return undefined;
        if (signal.aborted) {
          setState({ phase: "idle" });
          return undefined;
        }

        setState({ phase: "error", error: toApiError(error) });
        return undefined;
      } finally {
        if (inFlight.current === current) inFlight.current = null;
      }
    },
    [parentSignal],
  );

  const reset = useCallback(() => {
    if (mounted.current) setState({ phase: "idle" });
  }, []);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      generation.current += 1;
      const current = inFlight.current;
      inFlight.current = null;
      current?.controller.abort();
    };
  }, []);

  useEffect(() => {
    if (parentSignal === undefined) return;
    if (parentSignal.aborted) {
      cancel();
      return;
    }

    parentSignal.addEventListener("abort", cancel, { once: true });
    return () => parentSignal.removeEventListener("abort", cancel);
  }, [cancel, parentSignal]);

  return { state, pending: state.phase === "pending", run, cancel, reset };
}
