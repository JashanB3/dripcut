import { useEffect, useState } from "react";

import type { ProductRoute } from "../models";

const validRoutes = new Set<ProductRoute>([
  "home",
  "projects",
  "templates",
  "ai-editor",
  "auto-clip",
  "ai-thumbnail",
  "schedule",
  "settings",
]);

const readRoute = (): ProductRoute => {
  const value = window.location.hash.replace(/^#\/?/, "") as ProductRoute;
  return validRoutes.has(value) ? value : "home";
};

export function useHashRoute() {
  const [route, setRoute] = useState<ProductRoute>(readRoute);

  useEffect(() => {
    const onHashChange = () => setRoute(readRoute());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const navigate = (next: ProductRoute) => {
    window.location.hash = `/${next}`;
    setRoute(next);
  };

  return { route, navigate };
}
