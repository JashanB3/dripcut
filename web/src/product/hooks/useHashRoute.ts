import { useEffect, useState } from "react";

import { isLaunchRoute } from "../launch";
import type { ProductRoute } from "../models";

const validRoutes = new Set<ProductRoute>([
  "home",
  "projects",
  "templates",
  "ai-editor",
  "auto-clip",
  "ai-thumbnail",
  "script",
  "schedule",
  "usage",
  "admin",
  "settings",
]);

const routePaths: Record<ProductRoute, string> = {
  home: "/home",
  projects: "/projects",
  templates: "/templates",
  "ai-editor": "/ai-editor",
  "auto-clip": "/auto-clip",
  "ai-thumbnail": "/ai-thumbnail",
  script: "/script",
  schedule: "/schedule",
  usage: "/usage",
  admin: "/admin",
  settings: "/settings",
};

const readRoute = (): ProductRoute => {
  const pathname = window.location.pathname.replace(/^\/+|\/+$/g, "") as ProductRoute;
  if (pathname as string === "create") return "auto-clip";
  if (validRoutes.has(pathname)) return isLaunchRoute(pathname) ? pathname : "home";
  const value = window.location.hash.replace(/^#\/?/, "") as ProductRoute;
  return validRoutes.has(value) && isLaunchRoute(value) ? value : "home";
};

export function useHashRoute() {
  const [route, setRoute] = useState<ProductRoute>(readRoute);

  useEffect(() => {
    const onHashChange = () => setRoute(readRoute());
    window.addEventListener("hashchange", onHashChange);
    window.addEventListener("popstate", onHashChange);
    return () => {
      window.removeEventListener("hashchange", onHashChange);
      window.removeEventListener("popstate", onHashChange);
    };
  }, []);

  const navigate = (next: ProductRoute) => {
    next = isLaunchRoute(next) ? next : "home";
    window.history.pushState({}, "", routePaths[next]);
    window.location.hash = "";
    setRoute(next);
  };

  return { route, navigate };
}
