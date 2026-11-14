import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { ApiError, setImplementationListener, setUnauthenticatedListener } from "@/api/client";
import { keys } from "@/api/hooks";
import { App } from "@/app/App";
import { useUi } from "@/state/ui";
import "@/styles/app.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
      refetchOnWindowFocus: false,
    },
  },
});

setImplementationListener((i) => useUi.getState().setImplementation(i));
setUnauthenticatedListener(() => queryClient.setQueryData(keys.me, null));

const root = document.getElementById("root");
if (!root) throw new Error("missing #root");
createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
