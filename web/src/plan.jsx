import { useEffect, useMemo, useState } from "preact/hooks";
import { CCU_TOOL, ago, money } from "./app.jsx";

// The upgrade (CCU) planner: the cheapest way from a ship you own to the one you want, chaining upgrades on sale now
// and ones you already have. If every step were at full price a chain would cost the same as the full difference, so
// what a route saves is the discounts on its steps. The map comes from RSI's upgrade tool every few hours
// (/plan.json); the route is worked out here, so changing ships never waits on the server.

const OWNED_KEY = "pw-owned";  // upgrades you already have: [[from ship id, to ship id], ...], only in this browser
const slug = (t) => t.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
const step = (label) => (/upgrade$/i.test(label) ? label : `${label} upgrade`);
const ALTERNATIVES = 3;

function loadOwned() {
  try {
    const v = JSON.parse(localStorage.getItem(OWNED_KEY) || "[]");
    return Array.isArray(v) ? v.filter((p) => Array.isArray(p) && p.length === 2) : [];
  } catch { return []; }
}

export function Plan({ data }) {
  const [map, setMap] = useState(null);
  const [failed, setFailed] = useState(false);
  const [tries, setTries] = useState(0);
  useEffect(() => {
    setFailed(false);
    fetch("/plan.json").then((r) => (r.ok ? r.json() : Promise.reject(r.status))).then(setMap).catch(() => setFailed(true));
  }, [tries]);
  useEffect(() => { document.title = "Upgrade planner · Pledge Watch"; }, []);
  const now = Math.floor(Date.now() / 1000);
  return (
    <div class="page planner">
      <header class="top">
        <a class="mark" href="/" aria-label="Pledge Watch home">
          <svg viewBox="0 0 32 32" aria-hidden="true"><path d="M16 3 L26 28 L16 22 L6 28 Z" /></svg>
          Pledge Watch
        </a>
        <nav class="menu" aria-label="Pages">
          <a class="navbtn" href="/"><span aria-hidden="true">←</span> All ships</a>
        </nav>
      </header>
      <section class="lede">
        <h1>Plan an upgrade</h1>
        <p class="sub">
          The cheapest way from a ship you own to the one you want. Chaining upgrades (CCUs) through discounted ones
          can cost less than upgrading straight across.
        </p>
      </section>
      {map ? <Planner map={map} now={now} /> : failed ? (
        <p class="empty">Couldn't load the upgrade map. <button type="button" class="link" onClick={() => setTries((t) => t + 1)}>Try again</button></p>
      ) : <p class="empty">Loading the upgrade map…</p>}
      <footer>
        <p>
          Fan project, not affiliated with Cloud Imperium or Roberts Space Industries. Upgrade costs come from RSI's
          public upgrade tool, as seen logged out, in US dollars before tax. Upgrades you add as ones you already have
          stay in your browser. <a href="/privacy">Privacy</a> · <a href="/terms">Terms</a>
        </p>
      </footer>
    </div>
  );
}

function Planner({ map, now }) {
  const ships = useMemo(() => map.ships.map(([ref, name, value]) => ({ ref, name, value }))
    .sort((a, b) => a.name.localeCompare(b.name, "en", { numeric: true, sensitivity: "base" })), [map]);
  const byRef = useMemo(() => Object.fromEntries(ships.map((s) => [s.ref, s])), [ships]);
  const [from, setFrom] = useState(() => refOf(ships, "from"));
  const [to, setTo] = useState(() => refOf(ships, "to"));
  useEffect(() => {
    const p = new URLSearchParams();
    if (byRef[from]) p.set("from", slug(byRef[from].name));
    if (byRef[to]) p.set("to", slug(byRef[to].name));
    const qs = p.toString();
    history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
  }, [from, to]);
  const [owned, setOwned] = useState(loadOwned);
  const saveOwned = (list) => {
    setOwned(list);
    try { localStorage.setItem(OWNED_KEY, JSON.stringify(list)); } catch {}
  };
  const [showOwned, setShowOwned] = useState(false);

  // ship id -> the cheapest way to each ship it can upgrade into: { to, cost, label, owned }
  const edges = useMemo(() => {
    const best = {};
    const add = (f, e) => {
      const k = `${f}>${e.to}`;
      if (!best[k] || e.cost < best[k].cost) best[k] = { ...e, from: f };
    };
    for (const [f, list] of Object.entries(map.paths)) {
      for (const [sku, cost] of list) {
        const k = map.skus[sku];
        if (k && byRef[f] && byRef[k[0]]) add(+f, { to: k[0], cost, label: k[1] });
      }
    }
    for (const [f, t] of owned) if (byRef[f] && byRef[t]) add(f, { to: t, cost: 0, label: "", owned: true });
    const out = {};
    for (const e of Object.values(best)) (out[e.from] ||= []).push(e);
    return out;
  }, [map, owned, byRef]);

  const start = byRef[from], goal = byRef[to];
  const reach = useMemo(() => reachable(edges, from), [edges, from]);
  const found = useMemo(() => (start && goal ? routes(edges, from, to) : []), [edges, from, to]);
  const targets = ships.filter((s) => start && s.value > start.value);

  return (
    <>
      <div class="plan-pick">
        <label class="field">
          <span>I own</span>
          <select value={from} onChange={(e) => setFrom(Number(e.currentTarget.value) || "")}>
            <option value="">Pick your ship</option>
            {ships.map((s) => <option value={s.ref}>{s.name} ({money(s.value)})</option>)}
          </select>
        </label>
        <label class="field">
          <span>I want</span>
          <select value={to} disabled={!start} onChange={(e) => setTo(Number(e.currentTarget.value) || "")}>
            <option value="">{start ? "Pick the ship you want" : "Pick your ship first"}</option>
            {start ? (
              <>
                <optgroup label="Reachable now">
                  {targets.filter((s) => reach.has(s.ref)).map((s) => <option value={s.ref}>{s.name} ({money(s.value)})</option>)}
                </optgroup>
                <optgroup label="No route on sale right now">
                  {targets.filter((s) => !reach.has(s.ref)).map((s) => <option value={s.ref}>{s.name} ({money(s.value)})</option>)}
                </optgroup>
              </>
            ) : null}
          </select>
        </label>
        <button type="button" class="link owned-toggle" aria-expanded={showOwned} onClick={() => setShowOwned(!showOwned)}>
          {showOwned ? "Hide" : "Add"} upgrades I already have{owned.length ? ` (${owned.length})` : ""}
        </button>
        {showOwned ? <Owned ships={ships} byRef={byRef} owned={owned} save={saveOwned} /> : null}
      </div>

      {start && goal && goal.value <= start.value ? (
        <p class="empty">Upgrades only go up in value: pick a ship worth more than your {start.name}.</p>
      ) : start && goal ? (
        found.length ? <Result start={start} goal={goal} found={found} byRef={byRef} /> : (
          <p class="empty">
            No route from your {start.name} to the {goal.name} right now: nothing on sale connects them. Warbond and
            other sale upgrades come and go, so check back during sales. On Discord, <code>/watch from:{start.name}</code> pings
            you when an upgrade your ship can take comes in.
          </p>
        )
      ) : start ? (
        <p class="empty">Your {start.name} can reach {reach.size ? `${reach.size} ships` : "no ships"} with upgrades on sale now{owned.length ? " and the ones you have" : ""}. Pick one under I want.</p>
      ) : null}

      <p class="plan-note">
        {map.at ? `Upgrade costs from RSI's upgrade tool, updated ${ago(map.at, now)}. ` : "Still mapping RSI's upgrades; check back in a few minutes. "}
        Warbond upgrades have to be paid with new money, not store credit, and sale upgrades can sell out or end. Check
        the price in your hangar before you buy.
      </p>
    </>
  );
}

function refOf(ships, key) {
  const want = new URLSearchParams(location.search).get(key);
  return (want && ships.find((s) => slug(s.name) === want)?.ref) || "";
}

function reachable(edges, from) {
  const seen = new Set(), todo = [from];
  while (todo.length) for (const e of edges[todo.pop()] || []) if (!seen.has(e.to)) { seen.add(e.to); todo.push(e.to); }
  return seen;
}

// Cheapest (then fewest steps) way from every ship to `to`, searched backwards from it. Each way out of `from` that
// leads there then gives one route, so the alternatives start differently instead of being near copies of the best.
function routes(edges, from, to) {
  const incoming = {};
  for (const list of Object.values(edges)) for (const e of list) (incoming[e.to] ||= []).push(e);
  const better = (a, b) => !b || a.cost < b.cost || (a.cost === b.cost && a.steps < b.steps);
  const best = { [to]: { cost: 0, steps: 0, next: null } };
  const done = new Set();
  for (;;) {
    let cur = null;
    for (const k of Object.keys(best)) if (!done.has(k) && (cur === null || better(best[k], best[cur]))) cur = k;
    if (cur === null) break;
    done.add(cur);
    for (const e of incoming[cur] || []) {
      const c = { cost: best[cur].cost + e.cost, steps: best[cur].steps + 1, next: e };
      if (!done.has(String(e.from)) && better(c, best[e.from])) best[e.from] = c;
    }
  }
  return (edges[from] || []).filter((e) => best[e.to]).map((e) => {
    const hops = [e];
    while (hops[hops.length - 1].to !== to) hops.push(best[hops[hops.length - 1].to].next);
    return { hops, cost: hops.reduce((a, h) => a + h.cost, 0) };
  }).sort((a, b) => a.cost - b.cost || a.hops.length - b.hops.length);
}

function Result({ start, goal, found, byRef }) {
  const [best, ...rest] = found;
  const full = goal.value - start.value;
  const saves = full - best.cost;
  const direct = found.find((r) => r.hops.length === 1 && !r.hops[0].owned);
  return (
    <section class="route" aria-label="Best route">
      <div class="route-head">
        <span class="k">Best route</span>
        <b class="total">{money(best.cost)}</b>
        <span class="vs">
          {saves > 0 ? <><b class="saves">saves {money(saves)}</b> on the full difference of {money(full)}</> : `the full difference is ${money(full)}`}
          {direct && direct !== best ? ` · straight across on sale: ${money(direct.cost)}` : ""}
        </span>
      </div>
      <Steps start={start} route={best} byRef={byRef} />
      <a class="tool" href={CCU_TOOL} target="_blank" rel="noopener">Buy upgrades in your RSI hangar ↗</a>
      {rest.length ? (
        <details class="others">
          <summary>Other routes ({Math.min(rest.length, ALTERNATIVES)})</summary>
          {rest.slice(0, ALTERNATIVES).map((r) => (
            <div class="other">
              <p><b>{money(r.cost)}</b> · {r.hops.length === 1 ? "straight across" : `via ${r.hops.slice(0, -1).map((h) => byRef[h.to].name).join(", ")}`}</p>
              <Steps start={start} route={r} byRef={byRef} />
            </div>
          ))}
        </details>
      ) : null}
    </section>
  );
}

function Steps({ start, route, byRef }) {
  return (
    <ol class="steps">
      <li class="stop"><span class="nm">{start.name}</span><span class="v">{money(start.value)}</span></li>
      {route.hops.map((h) => (
        <>
          <li class="hop">
            {h.owned ? <>Your upgrade, already paid <b>$0</b></> : <>{step(h.label)} <b>{money(h.cost)}</b></>}
            {!h.owned && /warbond/i.test(h.label) ? <span class="tag wb">new money only</span> : null}
          </li>
          <li class="stop"><span class="nm">{byRef[h.to].name}</span><span class="v">{money(byRef[h.to].value)}</span></li>
        </>
      ))}
    </ol>
  );
}

// Upgrades bought earlier (in a sale, say) that are sitting in your hangar: each is a free step from one ship to another.
function Owned({ ships, byRef, owned, save }) {
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const up = ships.filter((s) => byRef[a] && s.value > byRef[a].value);
  const add = () => {
    if (!byRef[a] || !byRef[b] || owned.some(([x, y]) => x === a && y === b)) return;
    save([...owned, [a, b]]);
    setB("");
  };
  return (
    <div class="owned">
      {owned.length ? (
        <ul>
          {owned.map(([x, y], i) => (
            <li>
              <span>{byRef[x]?.name || "?"} → {byRef[y]?.name || "?"}</span>
              <button type="button" class="link" aria-label="Remove this upgrade" onClick={() => save(owned.filter((_, j) => j !== i))}>Remove</button>
            </li>
          ))}
        </ul>
      ) : <p class="muted">Bought an upgrade in an earlier sale? Add it here and routes can use it as a free step. It's saved in this browser only.</p>}
      <div class="owned-add">
        <select aria-label="Upgrade from" value={a} onChange={(e) => { setA(Number(e.currentTarget.value) || ""); setB(""); }}>
          <option value="">From…</option>
          {ships.map((s) => <option value={s.ref}>{s.name}</option>)}
        </select>
        <select aria-label="Upgrade to" value={b} disabled={!a} onChange={(e) => setB(Number(e.currentTarget.value) || "")}>
          <option value="">To…</option>
          {up.map((s) => <option value={s.ref}>{s.name}</option>)}
        </select>
        <button type="button" class="add" disabled={!a || !b} onClick={add}>Add</button>
      </div>
    </div>
  );
}
