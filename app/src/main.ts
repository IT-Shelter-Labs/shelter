import "./styles/app.css";
import "./styles/glass.css";
import { mount } from "svelte";
import App from "./App.svelte";

// В установленной версии — без браузерного контекстного меню и F5/Ctrl+P.
if (!import.meta.env.DEV) {
  window.addEventListener("contextmenu", (e) => {
    if (!(e.target as HTMLElement).closest("input, textarea, .selectable")) e.preventDefault();
  });
  window.addEventListener("keydown", (e) => {
    if (e.key === "F5" || (e.ctrlKey && ["p", "r", "f", "g", "u"].includes(e.key.toLowerCase()))) e.preventDefault();
  });
}

mount(App, { target: document.getElementById("app")! });
