import { EvalPage } from "./pages/EvalPage";
import { HomePage } from "./pages/HomePage";
import { RunPage } from "./pages/RunPage";
import { href, useRoute } from "./router";

export function App() {
  const route = useRoute();
  return (
    <>
      <header className="topbar">
        <a className="brand" href={href()}>
          Factory Triage Viewer<small>drone end-of-line test station</small>
        </a>
      </header>
      <main>
        {route.page === "home" && <HomePage />}
        {route.page === "eval" && <EvalPage name={route.name} />}
        {route.page === "evalRun" && <RunPage source={{ kind: "eval", ...route }} />}
        {route.page === "trace" && <RunPage source={{ kind: "trace", runId: route.runId }} />}
        {route.page === "notFound" && (
          <div className="empty">
            Page not found. <a href={href()}>Back to all runs</a>
          </div>
        )}
      </main>
    </>
  );
}
