import { render } from "preact";
import { App } from "./app.jsx";
import { Plan } from "./plan.jsx";
import "./style.css";

// The server puts the data in the page. `npm run dev` has none, so fetch it from the running bot instead.
// /plan is the upgrade planner: its page carries the planner's map instead of the ship list.
const root = document.getElementById("app");
const inline = (id) => { const el = document.getElementById(id); return el ? JSON.parse(el.textContent) : null; };
if (location.pathname === "/plan") render(<Plan map={inline("plan")} />, root);
else if (inline("data")) render(<App data={inline("data")} />, root);
else fetch("/ships.json").then((r) => r.json()).then((data) => render(<App data={data} />, root));
