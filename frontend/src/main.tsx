import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { StoreProvider } from "./state/store";
import { FeedbackProvider } from "./components/feedback";
import "./styles.css";

// Old links from the market pages use /?view=<name>; turn them into the hash route the app reads.
const legacyView = new URLSearchParams(window.location.search).get("view");
if (legacyView && !window.location.hash) window.history.replaceState(null, "", `/#${encodeURIComponent(legacyView)}`);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <FeedbackProvider>
      <StoreProvider>
        <App />
      </StoreProvider>
    </FeedbackProvider>
  </StrictMode>,
);
