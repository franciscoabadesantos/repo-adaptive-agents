// Loads the local visual theme used across the app.
import { createApp } from "vue";

export function installTheme() {
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = "/resources/theme/theme.css";
  document.head.appendChild(link);
}
