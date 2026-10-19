import { useEffect, useState } from "react";

export type Route =
  | { page: "home" }
  | { page: "eval"; name: string }
  | { page: "evalRun"; name: string; mode: string; runId: string }
  | { page: "trace"; runId: string }
  | { page: "notFound" };

/** Parse a hash such as `#/eval/2026-run/library/library-0003` into a route. */
export function parseHash(hash: string): Route {
  const parts = hash
    .replace(/^#\/?/, "")
    .split("/")
    .filter(Boolean)
    .map(decodeURIComponent);
  if (parts.length === 0) return { page: "home" };
  if (parts[0] === "eval" && parts.length === 2) return { page: "eval", name: parts[1] };
  if (parts[0] === "eval" && parts.length === 4)
    return { page: "evalRun", name: parts[1], mode: parts[2], runId: parts[3] };
  if (parts[0] === "trace" && parts.length === 2) return { page: "trace", runId: parts[1] };
  return { page: "notFound" };
}

export function href(...parts: string[]): string {
  return "#/" + parts.map(encodeURIComponent).join("/");
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseHash(window.location.hash));
  useEffect(() => {
    const onChange = () => {
      setRoute(parseHash(window.location.hash));
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}
