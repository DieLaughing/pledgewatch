import { render } from "preact";
import { App } from "./app.jsx";
import "./style.css";

// The server puts the data in the page. `npm run dev` has none, so fetch it from the running bot instead.
const inline = document.getElementById("data");
const start = (data) => render(<App data={data} />, document.getElementById("app"));
if (inline) start(JSON.parse(inline.textContent));
else fetch("/ships.json").then((r) => r.json()).then(start);
