import { useEffect } from "react";
import { useArchal } from "@/lib/store";

export function useHydrateArchal() {
  const setHydrated = useArchal((s) => s.setHydrated);
  useEffect(() => {
    void useArchal.persist.rehydrate();
    setHydrated(true);
  }, [setHydrated]);
}
