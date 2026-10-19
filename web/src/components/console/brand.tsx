import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { listBrands, type BrandRow } from "@/lib/ops";
import { useArchal } from "@/lib/store";

type BrandContextValue = {
  brandId: string;
  brand: BrandRow | null;
  brands: BrandRow[];
  setBrandId: (id: string) => void;
  error: string;
};

const BrandContext = createContext<BrandContextValue | null>(null);

export function BrandProvider({ children }: { children: ReactNode }) {
  const [brands, setBrands] = useState<BrandRow[]>([]);
  const [brandId, setBrandIdState] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    const saved = window.localStorage.getItem("archal-active-brand");
    if (saved) setBrandIdState(saved);
    listBrands()
      .then((rows) => {
        setBrands(rows);
        setBrandIdState(rows[0]?.id || "");
        setError("");
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "The desk could not load.");
      });
  }, []);

  function setBrandId(id: string) {
    setBrandIdState(id);
    window.localStorage.setItem("archal-active-brand", id);
    const state = useArchal.getState();
    if (state.brands.some((brand) => brand.id === id)) state.switchBrand(id);
  }

  const brand = brands.find((row) => row.id === brandId) ?? brands[0] ?? null;

  return (
    <BrandContext.Provider value={{ brandId: brand?.id ?? brandId, brand, brands, setBrandId, error }}>
      {children}
    </BrandContext.Provider>
  );
}

export function useBrand() {
  const value = useContext(BrandContext);
  if (!value) throw new Error("useBrand must be used in the console");
  return value;
}
