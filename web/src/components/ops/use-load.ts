import { useEffect, useState } from "react";

export function useLoad<T>(load: () => Promise<T>, deps: readonly unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancel = false;
    setLoading(true);
    load()
      .then((value) => {
        if (cancel) return;
        setData(value);
        setError("");
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancel) return;
        setError(err instanceof Error ? err.message : "Request failed.");
        setLoading(false);
      });
    return () => {
      cancel = true;
    };
    // load identity changes every render; callers pass deps instead.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, ...deps]);

  return {
    data,
    error,
    loading,
    reload: () => setTick((n) => n + 1),
  };
}
