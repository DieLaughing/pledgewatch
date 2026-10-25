import { useEffect, useMemo, useState } from "preact/hooks";

const FILTERS = [
  ["warbond", "Warbond", (s) => s.editions.some((e) => e.inStore && e.label === "Warbond")],
  ["anniversary", "10 Year", (s) => s.editions.some((e) => e.inStore && e.label === "10 Year")],
  ["lti", "Lifetime insurance", (s) => s.editions.some((e) => e.inStore && e.insurance === "Lifetime")],
  ["buyable", "Buy in game", (s) => !!s.buy],
  ["rentable", "Rent in game", (s) => !!s.rent],
  ["sale", "On sale", (s) => s.editions.some((e) => e.inStore && e.listPrice && e.price < e.listPrice)],
  ["limited", "Limited", (s) => s.editions.some((e) => e.inStore && e.limited)],
  ["concept", "Not flyable yet", (s) => s.status && s.status !== "Flight ready"],
];
const SIZES = ["Vehicle", "Snub", "Small", "Medium", "Large", "Capital"];
const SORTS = {
  "price-desc": ["Price, high to low", (a, b) => price(b) - price(a)],
  "price-asc": ["Price, low to high", (a, b) => (price(a) || 1e12) - (price(b) || 1e12)],
  name: ["Name", () => 0],
  size: ["Size", (a, b) => SIZES.indexOf(b.size) - SIZES.indexOf(a.size)],
  game: ["In-game price, low to high", (a, b) => (low(a.buy) || 1e15) - (low(b.buy) || 1e15)],
};
const low = (list) => (list && list.length ? Math.min(...list.map((x) => x[0])) : 0);
const auec = (n) => (n >= 1e6 ? `${+(n / 1e6).toFixed(n >= 1e7 ? 1 : 2)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : `${n}`) + " aUEC";
const RATE_KEY = "pw-rate";
function savedRate() {
  try { return Number(localStorage.getItem(RATE_KEY)) || 500000; } catch { return 500000; }
}
const KIND = {
  new: ["Came in", "good"], back: ["Back", "good"], restock: ["Restocked", "good"], low: ["Low stock", "warn"],
  sold_out: ["Sold out", "bad"], gone: ["Left the store", "bad"], price: ["Price", "info"],
  status: ["Flight status", "info"], loaners: ["Loaners", "info"],
};

const money = (c) => (c == null ? "" : "$" + (c / 100).toLocaleString("en-US", { maximumFractionDigits: c % 100 ? 2 : 0 }));
const price = (s) => {
  const v = Math.min(...s.editions.filter((e) => e.inStore).map((e) => e.price ?? Infinity));
  return Number.isFinite(v) ? v : 0;
};
const norm = (t) => t.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

function ago(ts, now) {
  const s = Math.max(0, now - ts);
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  const d = Math.round(s / 86400);
  return d < 60 ? `${d} day${d === 1 ? "" : "s"} ago` : `${Math.round(d / 30)} months ago`;
}

function readUrl() {
  const p = new URLSearchParams(location.search);
  return {
    view: p.get("view") === "all" ? "all" : p.get("view") === "changes" ? "changes" : "store",
    q: p.get("q") || "",
    f: (p.get("f") || "").split(",").filter((f) => FILTERS.some(([k]) => k === f)),
    maker: p.get("maker") || "",
    size: p.get("size") || "",
    sort: SORTS[p.get("sort")] ? p.get("sort") : "price-desc",
    from: (p.get("from") || "").replace(/-/g, " "),
  };
}

function writeUrl(s) {
  const p = new URLSearchParams();
  if (s.view !== "store") p.set("view", s.view);
  if (s.q) p.set("q", s.q);
  if (s.f.length) p.set("f", s.f.join(","));
  if (s.maker) p.set("maker", s.maker);
  if (s.size) p.set("size", s.size);
  if (s.sort !== "price-desc") p.set("sort", s.sort);
  if (s.from) p.set("from", s.from.replace(/ /g, "-"));
  const qs = p.toString();
  history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
}

export function App({ data }) {
  const [st, setSt] = useState(readUrl);
  const set = (patch) => setSt((s) => ({ ...s, ...patch }));
  useEffect(() => writeUrl(st), [st]);
  const now = Math.floor(Date.now() / 1000);

  const ships = data.ships;
  const inStore = useMemo(() => ships.filter((s) => s.inStore), [ships]);
  const makers = useMemo(() => [...new Set(ships.map((s) => s.maker).filter(Boolean))].sort(), [ships]);
  const counts = useMemo(() => Object.fromEntries(FILTERS.map(([k, , fn]) => [k, inStore.filter(fn).length])), [inStore]);

  const shown = useMemo(() => {
    const q = norm(st.q);
    const pool = st.view === "all" ? ships : inStore;
    const active = FILTERS.filter(([k]) => st.f.includes(k));
    return pool
      .filter((s) => !q || norm(`${s.name} ${s.maker} ${s.makerCode} ${s.role}`).includes(q))
      .filter((s) => active.every(([, , fn]) => fn(s)))
      .filter((s) => !st.maker || s.maker === st.maker)
      .filter((s) => !st.size || s.size === st.size)
      .sort((a, b) => SORTS[st.sort][1](a, b) || a.name.localeCompare(b.name));
  }, [ships, inStore, st]);

  const [rate, setRate] = useState(savedRate);
  const changeRate = (v) => {
    const n = Math.max(1000, Number(String(v).replace(/[^0-9]/g, "")) || 0);
    setRate(n);
    try { localStorage.setItem(RATE_KEY, String(n)); } catch {}
  };
  const upgradable = useMemo(() => inStore.filter((s) => s.editions.some((e) => e.inStore && e.label === "Standard"))
    .map((s) => [s.key, s.name, s.editions.find((e) => e.inStore && e.label === "Standard").price])
    .sort((a, b) => a[2] - b[2]), [inStore]);
  const fromPrice = (upgradable.find(([k]) => k === st.from) || [])[2] || 0;

  const toggle = (k) => set({ f: st.f.includes(k) ? st.f.filter((x) => x !== k) : [...st.f, k] });
  const clear = () => set({ q: "", f: [], maker: "", size: "" });
  const filtered = st.q || st.f.length || st.maker || st.size;

  return (
    <div class="page">
      <header class="top">
        <a class="mark" href="/" aria-label="Pledge Watch home">
          <svg viewBox="0 0 32 32" aria-hidden="true"><path d="M16 3 L26 28 L16 22 L6 28 Z" /></svg>
          Pledge Watch
        </a>
        <p class="checked">
          <span class="dot" aria-hidden="true" />
          Public RSI store{data.checkedAt ? `, checked ${ago(data.checkedAt, now)}` : ""}
        </p>
      </header>

      <section class="lede">
        <h1>
          <b>{inStore.length} ships</b> in the store.{" "}
          <span>
            {counts.warbond} with a warbond price, {counts.anniversary} anniversary editions, {counts.sale ? `${counts.sale} on sale` : "nothing on sale"}
            {counts.limited ? `, ${counts.limited} limited` : ""}.
          </span>
        </h1>
      </section>

      <nav class="tabs" aria-label="View">
        {[["store", `In the store · ${inStore.length}`], ["all", `All ships · ${ships.length}`], ["changes", `Changes · ${data.changes.length}`]].map(([v, label]) => (
          <button type="button" aria-pressed={st.view === v} onClick={() => set({ view: v })}>{label}</button>
        ))}
      </nav>

      {st.view === "changes" ? (
        <Changes data={data} now={now} />
      ) : (
        <>
          <div class="controls">
            <input id="q" type="search" placeholder="Search ships, makers, roles" value={st.q} aria-label="Search ships"
              onInput={(e) => set({ q: e.currentTarget.value })} />
            <div class="chips" role="group" aria-label="Show only">
              {FILTERS.map(([k, label]) => (
                <button type="button" class="chip" aria-pressed={st.f.includes(k)} onClick={() => toggle(k)}>
                  {label}{st.view === "store" ? <span class="n">{counts[k]}</span> : null}
                </button>
              ))}
            </div>
            <div class="selects">
              <select id="maker" aria-label="Maker" value={st.maker} onChange={(e) => set({ maker: e.currentTarget.value })}>
                <option value="">All makers</option>
                {makers.map((m) => <option value={m}>{m}</option>)}
              </select>
              <select id="size" aria-label="Size" value={st.size} onChange={(e) => set({ size: e.currentTarget.value })}>
                <option value="">All sizes</option>
                {SIZES.map((s) => <option value={s}>{s}</option>)}
              </select>
              <select id="sort" aria-label="Sort" value={st.sort} onChange={(e) => set({ sort: e.currentTarget.value })}>
                {Object.entries(SORTS).map(([k, [label]]) => <option value={k}>{label}</option>)}
              </select>
              <select id="from" aria-label="Upgrade from a ship you own" value={st.from} onChange={(e) => set({ from: e.currentTarget.value })}>
                <option value="">Upgrade from…</option>
                {upgradable.map(([k, name, p]) => <option value={k}>{`${name} (${money(p)})`}</option>)}
              </select>
              <label class="rate" for="rate">
                I earn
                <input id="rate" inputMode="numeric" value={rate.toLocaleString("en-US")} onChange={(e) => changeRate(e.currentTarget.value)} />
                aUEC an hour
              </label>
            </div>
          </div>

          <p class="count">
            {shown.length} {shown.length === 1 ? "ship" : "ships"}
            {filtered ? <button type="button" class="link" onClick={clear}>Clear filters</button> : null}
          </p>

          {shown.length ? (
            <ul class="ships">{shown.map((s) => <Ship ship={s} now={now} rate={rate} from={st.from} fromPrice={fromPrice} version={data.gameVersion} />)}</ul>
          ) : (
            <p class="empty">
              {st.f.includes("sale") || st.f.includes("limited")
                ? "Nothing like that in the store right now. The Discord and Fluxer bot posts the moment it changes."
                : "No ship matches. Try fewer filters or part of a name."}
            </p>
          )}
        </>
      )}

      <footer>
        <p>
          Fan project, not affiliated with Cloud Imperium or Roberts Space Industries. Prices are the public store in US
          dollars before tax, as seen logged out, so Concierge and subscriber early access isn't included. Checked every 5
          minutes. Ship details from RSI's Ship Matrix and Loaner Ship Matrix. Cargo grids from{" "}
          <a href="https://sc-cargo.space" target="_blank" rel="noopener">sc-cargo.space</a> (<a href="https://github.com/sccargospace/sc-cargo.space/blob/main/LICENSE" target="_blank" rel="noopener">MIT licence</a>).
          In-game buy and rent prices from <a href="https://uexcorp.space" target="_blank" rel="noopener">UEX</a>. Insurance times and
          pledge price history from the <a href="https://starcitizen.tools" target="_blank" rel="noopener">Star Citizen Wiki</a>{" "}
          (<a href="https://creativecommons.org/licenses/by-sa/4.0/" target="_blank" rel="noopener">CC BY-SA 4.0</a>)
          {data.gameVersion ? `, game version ${data.gameVersion}` : ""}. Your aUEC-an-hour figure stays in your browser.
        </p>
        <p>No accounts, no cookies, no tracking. <a href="/ships.json">The data as JSON</a>.</p>
      </footer>
    </div>
  );
}

function Ship({ ship: s, now, rate, from, fromPrice, version }) {
  const standard = s.editions.find((e) => e.inStore && e.label === "Standard");
  const anchor = s.key.replace(/ /g, "-");
  const [open, setOpen] = useState(() => location.hash === `#${anchor}`);
  useEffect(() => { if (open && location.hash === `#${anchor}`) document.getElementById(anchor)?.scrollIntoView(); }, []);
  const specs = [s.maker, s.role, s.size, s.crew && `crew ${s.crew}`, s.cargo ? `${s.cargo.toLocaleString("en-US")} SCU` : ""]
    .filter(Boolean).join(" · ");
  const notFlyable = s.status && s.status !== "Flight ready";
  const upgrade = from && from !== s.key && standard && fromPrice && standard.price > fromPrice ? standard.price - fromPrice : 0;
  const buy = low(s.buy), rent = low(s.rent);
  return (
    <li id={anchor} class={`ship${s.inStore ? "" : " off"}`}>
      {s.img ? <img src={s.img} alt="" width="160" height="90" loading="lazy" decoding="async" /> : <div class="noimg" />}
      <div class="info">
        <h2>
          {s.rsi ? <a href={s.rsi} target="_blank" rel="noopener">{s.name}</a> : s.name}
          <a class="here" href={`#${anchor}`} aria-label={`Link to ${s.name}`}>#</a>
        </h2>
        <p class="specs">{specs}</p>
        {notFlyable ? (
          <p class="status">
            <span class="tag concept">{s.status}</span>
            {s.loaners ? ` Loaners: ${s.loaners}` : ""}
          </p>
        ) : null}
        <button type="button" class="link grid-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? "Hide details" : "Details"}
        </button>
      </div>
      <div class="buy">
        {s.editions.filter((e) => e.inStore).map((e) => <Edition e={e} standard={standard} upgrade={e === standard ? upgrade : 0} />)}
        {buy ? (
          <div class="ed ed-game" title="Lowest in-game buy price">
            <span class="label">In game</span>
            <span class="price">{auec(buy)}</span>
            <span class="ins">≈ {hours(buy / rate)} of play</span>
          </div>
        ) : rent ? (
          <div class="ed ed-game" title="Lowest in-game rental">
            <span class="label">Rent in game</span>
            <span class="price">{auec(rent)}</span>
            <span class="ins">per day</span>
          </div>
        ) : null}
        {!s.inStore ? (
          <p class="notin">
            Not in the store
            {s.editions.length ? `, last seen ${ago(Math.max(...s.editions.map((e) => e.lastSeen)), now)}` : ""}
          </p>
        ) : null}
      </div>
      {open ? <Details s={s} rate={rate} version={version} /> : null}
    </li>
  );
}

function hours(h) {
  if (h < 1) return `${Math.max(5, Math.round(h * 60 / 5) * 5)} min`;
  return h < 10 ? `${+h.toFixed(1)} h` : `${Math.round(h)} h`;
}

function Details({ s, rate, version }) {
  const pledge = Math.min(...s.editions.filter((e) => e.inStore).map((e) => e.price), Infinity);
  const lastPrice = s.history?.length ? s.history[s.history.length - 1][1] * 100 : 0;
  const dollars = (Number.isFinite(pledge) ? pledge : lastPrice) / 100;
  const buy = low(s.buy);
  const wb = (s.history || []).filter((h) => h[2]);
  const lowestWb = wb.length ? wb.reduce((a, b) => (b[1] < a[1] ? b : a)) : null;
  const lastWb = wb.length ? wb[wb.length - 1] : null;
  const month = (d) => new Date(d + "T00:00:00Z").toLocaleDateString("en-US", { month: "short", year: "numeric", timeZone: "UTC" });
  return (
    <div class="details">
      <section>
        <h3>In game</h3>
        {buy ? (
          <>
            <p><b>Buy for {auec(buy)}</b> at {s.buy.find((x) => x[0] === buy)[1]}{s.buy.length > 1 ? `, or ${s.buy.length - 1} other place${s.buy.length > 2 ? "s" : ""}` : ""}.</p>
            <p>At {auec(rate)} an hour that's <b>about {hours(buy / rate)}</b> of play
              {dollars ? `, or roughly ${Math.round(buy / dollars).toLocaleString("en-US")} aUEC for each dollar of its $${dollars.toLocaleString("en-US")} pledge price` : ""}.</p>
          </>
        ) : (
          <p>Not sold in game right now. New ships usually reach the pledge store long before they're sold in game.</p>
        )}
        {s.rent ? <p>Rent from <b>{auec(low(s.rent))}</b> a day at {s.rent.find((x) => x[0] === low(s.rent))[1]}{s.rent.length > 1 ? ` (${s.rent.length} places)` : ""}.</p> : null}
        {s.buy && s.buy.length > 1 ? (
          <ul class="where">{s.buy.map(([p, t]) => <li><span>{t}</span><span>{auec(p)}</span></li>)}</ul>
        ) : null}
      </section>

      <section>
        <h3>Insurance</h3>
        {s.insurance ? (
          <p>Claim takes <b>{s.insurance.claim} min</b>. Expedite: {s.insurance.expedite} min for <b>{s.insurance.expediteCost.toLocaleString("en-US")} aUEC</b>.
            {version ? <span class="muted"> Game {version}.</span> : null}</p>
        ) : <p class="muted">No claim times known for this ship yet.</p>}
        {s.editions.some((e) => e.inStore && e.insurance) ? (
          <p>In the store: {s.editions.filter((e) => e.inStore && e.insurance).map((e) => `${e.label} ${e.insurance === "Lifetime" ? "lifetime" : e.insurance}`).join(", ")}.</p>
        ) : null}
        {s.loaners ? <p>Loaners until it flies: {s.loaners}.</p> : null}
      </section>

      {s.history && s.history.length ? (
        <section>
          <h3>Price history</h3>
          <p>
            {lowestWb ? <>Lowest warbond <b>${lowestWb[1]}</b> ({month(lowestWb[0])}), last warbond <b>${lastWb[1]}</b> ({month(lastWb[0])}).</> : "No warbond seen for this ship."}
          </p>
          <ul class="hist">
            {[...s.history].reverse().slice(0, 12).map(([d, p, w, src]) => (
              <li>
                <span>{month(d)}</span>
                <span class={w ? "wb" : ""}>{w ? "Warbond" : "Standard"}{src === "upgrade" ? <i> upgrade</i> : null}</span>
                <span>${p.toLocaleString("en-US")}</span>
              </li>
            ))}
          </ul>
          <p class="muted small">"Upgrade" rows are the ship's value in RSI's upgrade (CCU) store, which can differ from the store price.</p>
        </section>
      ) : null}

      {s.grid ? <Grid grid={s.grid} /> : null}

      <p class="links">
        {s.rsi ? <a href={s.rsi} target="_blank" rel="noopener">RSI page</a> : null}
        <a href={`https://starcitizen.tools/index.php?search=${encodeURIComponent(s.name)}`} target="_blank" rel="noopener">Star Citizen Wiki</a>
        {s.grid ? <a href={s.grid.viewer} target="_blank" rel="noopener">3D cargo</a> : null}
      </p>
    </div>
  );
}

// Top-down floor plan of the cargo grid, every box labelled width × length × height in SCU. Data: sc-cargo.space (MIT).
function Grid({ grid }) {
  // Long ships are drawn lying down so the plan uses the page's width. Labels keep each box's own dimensions.
  const tall = (() => {
    const xs = grid.boxes.flatMap((x) => [x[0], x[0] + x[3]]), zs = grid.boxes.flatMap((x) => [x[1], x[1] + x[4]]);
    return Math.max(...zs) - Math.min(...zs) > (Math.max(...xs) - Math.min(...xs)) * 1.3;
  })();
  const b = tall ? grid.boxes.map(([x, z, y, bw, bl, bh]) => [z, x, y, bl, bw, bh, `${bw}×${bl}×${bh}`]) : grid.boxes;
  const minX = Math.min(...b.map((x) => x[0])), minZ = Math.min(...b.map((x) => x[1]));
  const maxX = Math.max(...b.map((x) => x[0] + x[3])), maxZ = Math.max(...b.map((x) => x[1] + x[4]));
  const maxH = Math.max(...b.map((x) => x[2] + x[5]));
  const w = maxX - minX, h = maxZ - minZ, pad = Math.max(w, h) * 0.02;
  const span = Math.max(w, h);
  // Label the biggest box in each spot; a smaller box underneath or on top of it would print over its label.
  const labelled = new Set(), taken = [];
  [...b.keys()].sort((i, j) => b[j][3] * b[j][4] - b[i][3] * b[i][4]).forEach((i) => {
    const [x, z, , bw, bl] = b[i];
    const cx = x + bw / 2, cz = z + bl / 2;
    if (taken.some(([tx, tz, tw, tl]) => cx > tx && cx < tx + tw && cz > tz && cz < tz + tl)) return;
    if (taken.some(([tx, tz, tw, tl]) => tx + tw / 2 > x && tx + tw / 2 < x + bw && tz + tl / 2 > z && tz + tl / 2 < z + bl)) return;
    labelled.add(i);
    taken.push([x, z, bw, bl]);
  });
  // Same-size boxes are grouped in the list: "2 × 6 × 12 × 4 = 576 SCU".
  const groups = {};
  for (const [, , , bw, bl, bh] of grid.boxes) {
    const k = `${bw} × ${bl} × ${bh}`;
    groups[k] = (groups[k] || 0) + 1;
  }
  const rows = Object.entries(groups).sort((a, z) => scu(z[0]) - scu(a[0]));
  return (
    <figure class="grid">
      <svg viewBox={`${minX - pad} ${minZ - pad} ${w + pad * 2} ${h + pad * 2}`} role="img"
        aria-label={`Cargo grid, ${grid.scu} SCU, seen from above`} preserveAspectRatio="xMidYMid meet">
        {b.map(([x, z, y, bw, bl, bh]) => (
          <rect x={x} y={z} width={bw} height={bl} style={`fill-opacity:${0.35 + 0.5 * ((y + bh) / maxH)}`} />
        ))}
        {b.map(([x, z, , bw, bl, bh, label], i) => {
          const size = Math.min(bw, bl) * 0.3;
          if (!labelled.has(i) || size < span * 0.022) return null;
          return (
            <text x={x + bw / 2} y={z + bl / 2} font-size={Math.min(size, span * 0.05)} text-anchor="middle" dominant-baseline="central">
              {label || `${bw}×${bl}×${bh}`}
            </text>
          );
        })}
      </svg>
      <figcaption>
        <ul class="boxes">
          {rows.map(([dims, n]) => (
            <li><b>{n} ×</b> {dims} <span>= {(n * scu(dims)).toLocaleString("en-US")} SCU</span></li>
          ))}
        </ul>
        <p>
          {grid.scu.toLocaleString("en-US")} SCU in total{grid.concept ? " (concept layout)" : ""}. Boxes are width × length × height in SCU,
          seen from above; darker means stacked higher.{" "}
          <a href={grid.viewer} target="_blank" rel="noopener">3D view on sc-cargo.space</a>
        </p>
      </figcaption>
    </figure>
  );
}

const scu = (dims) => dims.split(" × ").reduce((a, n) => a * Number(n), 1);

function Edition({ e, standard, upgrade }) {
  const saving = e.label !== "Standard" && standard && e.price < standard.price ? standard.price - e.price : 0;
  const onSale = e.listPrice && e.price < e.listPrice;
  const state = !e.available ? "Sold out" : e.limited ? `Limited${e.level ? `, ${e.level}` : ""}` : "";
  return (
    <a class={`ed ed-${e.label.replace(/\s+/g, "").toLowerCase()}${e.available ? "" : " soldout"}`} href={e.url} target="_blank" rel="noopener">
      <span class="label">{e.label}</span>
      <span class="price">
        {onSale ? <s>{money(e.listPrice)}</s> : null}
        {money(e.price)}
      </span>
      {e.insurance ? <span class={`ins${e.insurance === "Lifetime" ? " lti" : ""}`}>{e.insurance === "Lifetime" ? "Lifetime insurance" : `${e.insurance} insurance`}</span> : null}
      {e.paints ? <span class="extra" title={e.includes.join(", ")}>+ {e.paints} paint{e.paints === 1 ? "" : "s"}</span> : null}
      {saving ? <span class="save">save {money(saving)}</span> : null}
      {upgrade ? <span class="up">upgrade +{money(upgrade)}</span> : null}
      {state ? <span class="state">{state}</span> : null}
    </a>
  );
}

function Changes({ data, now }) {
  if (!data.changes.length) {
    return (
      <p class="empty">
        No changes yet. Tracking started {data.trackingSince ? ago(data.trackingSince, now) : "recently"}. Ships coming in,
        selling out, changing price or leaving will be listed here, newest first.
      </p>
    );
  }
  return (
    <ul class="changes">
      {data.changes.map((c) => {
        const [label, tone] = KIND[c.kind] || [c.kind, "info"];
        return (
          <li>
            <time datetime={new Date(c.ts * 1000).toISOString()}>{ago(c.ts, now)}</time>
            <span class={`pill ${tone}`}>{label}</span>
            {c.url ? <a href={c.url} target="_blank" rel="noopener">{c.name}</a> : <span class="nm">{c.name}</span>}
            {c.kind === "status" || c.kind === "loaners" ? (
              <span class="amt txt">{c.was ? `${c.was} → ` : ""}{c.now || "none listed"}</span>
            ) : (
              <span class="amt">
                {c.kind === "price" && c.was ? <s>{money(c.was)}</s> : null}
                {money(c.price)}
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}
