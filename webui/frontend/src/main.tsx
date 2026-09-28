import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { SubmissionStatus } from "./components/SubmissionStatus";
import "./styles.css";
import { initializeAppearance } from "./appearance";

initializeAppearance();

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <SubmissionStatus />
    <App />
  </StrictMode>,
);
