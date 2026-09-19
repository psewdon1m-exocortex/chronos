import "./update-overlay.css";
import { openUpdateOverlay, updateCookieHeaders } from "./update-overlay.js";

export function openChronosUpdates(component: "chronos" | "updater" | "neptune" | "gryphon" = "chronos") {
  return openUpdateOverlay({ service: "chronos", component, base: "/api/update-flow",
    headers: () => updateCookieHeaders(["chronos_csrf"], "X-CSRF-Token") });
}
