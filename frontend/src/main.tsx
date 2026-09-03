import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { ResumeDashboard } from "./components/ResumeDashboard";
import { initTheme } from "./lib/theme";
import "./styles/base.css";

// Before the first render, so the page never flashes light on the way to dark.
initTheme();

const root = document.getElementById("root");
if (!root) throw new Error("The #root element is missing from index.html.");

createRoot(root).render(
  <StrictMode>
    <ResumeDashboard />
  </StrictMode>,
);
