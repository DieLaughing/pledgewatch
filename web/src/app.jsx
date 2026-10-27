import { useEffect, useMemo, useRef, useState } from "preact/hooks";

const FILTERS = [
  ["warbond", "Warbond", (s) => s.editions.some((e) => e.inStore && e.label === "Warbond"), "editions"],
  ["anniversary", "10 Year", (s) => s.editions.some((e) => e.inStore && e.label === "10 Year"), "editions"],
  ["lti", "Lifetime insurance", (s) => s.editions.some((e) => e.inStore && e.insurance === "Lifetime"), "editions"],
  ["buyable", "Buy in game", (s) => !!s.buy, "game"],
  ["rentable", "Rent in game", (s) => !!s.rent, "game"],
  ["sale", "Discounted", (s) => s.editions.some((e) => e.inStore && e.listPrice && e.price < e.listPrice), "editions"],
  ["limited", "Limited stock", (s) => s.editions.some((e) => e.inStore && e.limited), "editions"],
  // How RSI sells the ship, as the Star Citizen Wiki records it (RSI doesn't say).
  ["always", "Always in store", (s) => s.sold === "always", "sold"],
  ["saleonly", "Sale only", (s) => s.sold === "time" || s.sold === "quantity", "sold"],
  ["gold", "Gold standard", (s) => s.gold?.status === "done", "ship"],
  ["concept", "Not flyable yet", (s) => s.status && s.status !== "Flight ready", "ship"],
  // Upgrade (CCU) store. With a ship picked under "Upgrade from", only upgrades that ship can actually take count.
  ["deals", "Upgrade deals", (s, x) => ups(s, x).some((u) => s.ccu && u.price < s.ccu.value), "upgrades"],
  ["ccu", "Upgradable", (s, x) => ups(s, x).length > 0, "upgrades"],
];
const GROUPS = [["editions", "Editions"], ["sold", "How it's sold"], ["upgrades", "Upgrades"], ["game", "In game"], ["ship", "Ship"]];
const SOLD = {
  time: ["Sale only", "Sold only during limited-time sales"],
  quantity: ["Limited runs", "Sold only in limited-quantity sales"],
};
const WIKI_GUESS = "according to the Star Citizen Wiki, which players keep from past sales. RSI doesn't confirm it, so it can be wrong or out of date";
// Upgrade filters also look at ships you can only get by upgrading right now, not as a standalone ship.
const UPGRADE_FILTERS = ["deals", "ccu"];
const ups = (s, x) => (s.upgrades || []).filter((u) => !x?.costs || (x.from !== s.key && u.sku in x.costs));
const SIZES = ["Vehicle", "Snub", "Small", "Medium", "Large", "Capital"];
// Release patch '3.24.3' -> comparable numbers; ships without one (concepts, unknown) sort last.
const rel = (s) => (s.released ? s.released.split(".").map(Number) : null);
const byRelease = (a, b) => {
  const x = rel(a), y = rel(b);
  if (!x || !y) return (x ? -1 : 0) + (y ? 1 : 0);
  for (let i = 0; i < Math.max(x.length, y.length); i++) if ((y[i] || 0) !== (x[i] || 0)) return (y[i] || 0) - (x[i] || 0);
  return 0;
};
const SORTS = {
  released: ["Newest release first", byRelease],
  "price-desc": ["Price, high to low", (a, b) => price(b) - price(a)],
  "price-asc": ["Price, low to high", (a, b) => (price(a) || 1e12) - (price(b) || 1e12)],
  name: ["Name", () => 0],
  size: ["Size, largest first", (a, b) => SIZES.indexOf(b.size) - SIZES.indexOf(a.size)],
  game: ["In-game price, low to high", (a, b) => (low(a.buy) || 1e15) - (low(b.buy) || 1e15)],
  "game-desc": ["In-game price, high to low", (a, b) => (low(b.buy) || -1) - (low(a.buy) || -1)],
  value: ["Value, most aUEC per pledge dollar", (a, b) => value(b) - value(a)],
  pilot: ["Pilot firepower, high to low", (a, b) => (b.weapons?.pilot[0] ?? -1) - (a.weapons?.pilot[0] ?? -1)],
};
// In-game buy price per pledge dollar: the lowest price in the store now, else the last price the wiki saw. 0 = unknown.
const pledgeDollars = (s) => (price(s) || (s.history?.length ? s.history[s.history.length - 1][1] * 100 : 0)) / 100;
const value = (s) => (low(s.buy) && pledgeDollars(s) ? low(s.buy) / pledgeDollars(s) : 0);
const low = (list) => (list && list.length ? Math.min(...list.map((x) => x[0])) : 0);
const auec = (n) => (n >= 1e6 ? `${+(n / 1e6).toFixed(n >= 1e7 ? 1 : 2)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : `${n}`) + " aUEC";
const RATE_KEY = "pw-rate";
export const CCU_TOOL = "https://robertsspaceindustries.com/en/account/pledges";  // My Hangar, where RSI's Ship Upgrade tool opens
const SEEN_KEY = "pw-seen";  // newest What's new date this browser has opened
function savedRate() {
  try { return Number(localStorage.getItem(RATE_KEY)) || 500000; } catch { return 500000; }
}
const KIND = {
  new: ["Came in", "good"], back: ["Back", "good"], restock: ["Restocked", "good"], low: ["Low stock", "warn"],
  sold_out: ["Sold out", "bad"], gone: ["Left the store", "bad"], price: ["Price", "info"],
  status: ["Flight status", "info"], loaners: ["Loaners", "info"],
};

export const money = (c) => (c == null ? "" : "$" + (c / 100).toLocaleString("en-US", { maximumFractionDigits: c % 100 ? 2 : 0 }));
const price = (s) => {
  const v = Math.min(...s.editions.filter((e) => e.inStore).map((e) => e.price ?? Infinity));
  return Number.isFinite(v) ? v : 0;
};
const norm = (t) => t.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
const planLink = (to, from) => `/plan?${from ? `from=${norm(from).replace(/ /g, "-")}&` : ""}to=${norm(to).replace(/ /g, "-")}`;

export function ago(ts, now) {
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

// While the tab stays open, fetch fresh data every 5 minutes and when the tab comes back into view, so an old tab
// never shows hour-old prices. Cloudflare caches /ships.json for a minute, so this costs the server almost nothing.
const REFRESH_MS = 5 * 60 * 1000;

export function App({ data: first }) {
  const [data, setData] = useState(first);
  useEffect(() => {
    let last = Date.now();
    const pull = () => {
      if (document.hidden) return;
      last = Date.now();
      fetch("/ships.json").then((r) => (r.ok ? r.json() : null)).then((d) => d && setData(d)).catch(() => {});
    };
    const timer = setInterval(pull, REFRESH_MS);
    const onShow = () => { if (!document.hidden && Date.now() - last > 60 * 1000) pull(); };
    document.addEventListener("visibilitychange", onShow);
    return () => { clearInterval(timer); document.removeEventListener("visibilitychange", onShow); };
  }, []);
  const [st, setSt] = useState(readUrl);
  const set = (patch) => setSt((s) => ({ ...s, ...patch }));
  useEffect(() => writeUrl(st), [st]);
  const now = Math.floor(Date.now() / 1000);

  const ships = data.ships;
  const inStore = useMemo(() => ships.filter((s) => s.inStore), [ships]);
  const makers = useMemo(() => [...new Set(ships.map((s) => s.maker).filter(Boolean))].sort(), [ships]);
  const sellable = useMemo(() => ships.filter((s) => s.inStore || s.upgrades), [ships]);

  // Picking a ship under "Upgrade from" asks the server what it can upgrade into right now (RSI's upgrade tool).
  const fromShip = ships.find((s) => s.key === st.from);
  const ref = fromShip?.ccu?.ref;
  // Tries a few times before giving up, and says so: rough estimates are only shown, marked ≈, when RSI can't be reached.
  const [costs, setCosts] = useState({ ref: null, map: null, state: "" });
  const [tries, setTries] = useState(0);
  useEffect(() => {
    if (!ref) return;
    let live = true;
    setCosts({ ref, map: null, state: "loading" });
    const get = (n) => fetch(`/upgrades/${ref}.json`).then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d) => live && setCosts({ ref, map: d.costs, state: "ok" }))
      .catch(() => {
        if (!live) return;
        if (n < 2) setTimeout(() => live && get(n + 1), 1500 * (n + 1));
        else setCosts({ ref, map: null, state: "error" });
      });
    get(0);
    return () => { live = false; };
  }, [ref, tries]);
  const lookup = ref && costs.ref === ref ? costs.state : "";
  const ctx = useMemo(() => ({ from: st.from, costs: lookup === "ok" ? costs.map : null, estimate: !ref || lookup === "error" }),
    [st.from, ref, costs, lookup]);

  const counts = useMemo(() => Object.fromEntries(FILTERS.map(([k, , fn]) =>
    [k, (UPGRADE_FILTERS.includes(k) ? sellable : inStore).filter((s) => fn(s, ctx)).length])), [inStore, sellable, ctx]);

  const shown = useMemo(() => {
    const q = norm(st.q);
    const active = FILTERS.filter(([k]) => st.f.includes(k));
    const pool = st.view === "all" ? ships : active.some(([k]) => UPGRADE_FILTERS.includes(k)) ? sellable : inStore;
    return pool
      .filter((s) => !q || norm(`${s.name} ${s.maker} ${s.makerCode} ${s.role}`).includes(q))
      .filter((s) => active.every(([, , fn]) => fn(s, ctx)))
      .filter((s) => !st.maker || s.maker === st.maker)
      .filter((s) => !st.size || s.size === st.size)
      .sort((a, b) => SORTS[st.sort][1](a, b) || a.name.localeCompare(b.name));
  }, [ships, inStore, sellable, st, ctx]);

  const [rate, setRate] = useState(savedRate);
  const changeRate = (v) => {
    const n = Math.max(1000, Number(String(v).replace(/[^0-9]/g, "")) || 0);
    setRate(n);
    try { localStorage.setItem(RATE_KEY, String(n)); } catch {}
  };
  // Ships you might own, valued as RSI's upgrade tool values them; failing that, at their standard price in the store
  // now, else the latest standard price seen in the pledge or upgrade store (the wiki's history).
  const upgradable = useMemo(() => ships.map((s) => {
    if (s.ccu) return [s.key, s.name, s.ccu.value, ""];
    const std = s.editions.find((e) => e.inStore && e.label === "Standard");
    if (std) return [s.key, s.name, std.price, ""];
    const last = (s.history || []).filter((h) => !h[2]).pop();
    return last ? [s.key, s.name, last[1] * 100, last[0]] : null;
  }).filter(Boolean).sort((a, b) => a[1].localeCompare(b[1], "en", { numeric: true, sensitivity: "base" })), [ships]);
  const fromPrice = (upgradable.find(([k]) => k === st.from) || [])[2] || 0;

  const toggle = (k) => set({ f: st.f.includes(k) ? st.f.filter((x) => x !== k) : [...st.f, k] });
  const clear = () => set({ q: "", f: [], maker: "", size: "", from: "" });
  const filtered = st.q || st.f.length || st.maker || st.size || st.from;
  // Filters live in a panel (a sheet from the bottom on phones). What's on shows as chips you can tap to remove.
  const sheet = useRef(null);
  const on = [
    ...(st.from && fromShip ? [[`From ${fromShip.name}`, () => set({ from: "" })]] : []),
    ...FILTERS.filter(([k]) => st.f.includes(k)).map(([k, label]) => [label, () => toggle(k)]),
    ...(st.maker ? [[st.maker, () => set({ maker: "" })]] : []),
    ...(st.size ? [[st.size, () => set({ size: "" })]] : []),
  ];
  const pickShip = () => { sheet.current?.showModal(); document.getElementById("from")?.focus(); };
  const [seen, setSeen] = useState(() => { try { return localStorage.getItem(SEEN_KEY) || ""; } catch { return ""; } });
  const markSeen = () => { try { localStorage.setItem(SEEN_KEY, data.newest); } catch {} setSeen(data.newest); };

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
        <nav class="menu" aria-label="Pages">
          <a class="navbtn" href="/whats-new" onClick={markSeen}>
            What's new{data.newest && seen < data.newest ? <span class="nd" aria-label="(new)" /> : null}
          </a>
          <a class="navbtn" href="/plan">Upgrade planner <span aria-hidden="true">→</span></a>
        </nav>
      </header>

      <section class="lede">
        <h1>
          <b>{inStore.length} ships</b> in the store.{" "}
          <span>
            {counts.warbond} with a warbond price, {counts.anniversary} with a 10 Year edition, {counts.sale ? `${counts.sale} discounted` : "no discounts right now"}
            {counts.limited ? `, ${counts.limited} limited` : ""}.
          </span>
        </h1>
      </section>

      {data.invite ? (
        <aside class="invite">
          <div>
            <b>Store alerts in your Discord</b>
            <span>Pledge Watch posts when ships come in, sell out or change price, and pings people for the ships they <code>/watch</code>. After adding it, an admin runs <code>/alerts setup</code> to pick the channel.</span>
          </div>
          {data.inviteFull
            ? <span class="full">Full for now: the bot is at its server limit.</span>
            : <a class="btn" href={data.invite} target="_blank" rel="noopener">Add to Discord</a>}
        </aside>
      ) : null}

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
            <div class="bar">
              <input id="q" type="search" placeholder="Search ships, makers, roles" value={st.q} aria-label="Search ships"
                onInput={(e) => set({ q: e.currentTarget.value })} />
              <button type="button" class="fbtn" aria-haspopup="dialog" onClick={() => sheet.current?.showModal()}>
                Filters{on.length ? <span class="badge">{on.length}</span> : null}
              </button>
            </div>
            {on.length ? (
              <div class="on" aria-label="Filters on">
                {on.map(([label, off]) => <button type="button" class="chip" aria-pressed="true" onClick={off} aria-label={`Remove ${label}`}>{label} <span aria-hidden="true">✕</span></button>)}
              </div>
            ) : null}
            {lookup === "loading" ? <p class="lookup">Asking RSI what your {fromShip.name} can upgrade into…</p> : null}
            {lookup === "error" ? (
              <p class="lookup bad">
                Couldn't reach RSI's upgrade tool, so upgrade costs below are rough estimates (≈).{" "}
                <button type="button" class="link" onClick={() => setTries((t) => t + 1)}>Try again</button>
              </p>
            ) : null}
            <div class="count">
              <span>{shown.length} {shown.length === 1 ? "ship" : "ships"}</span>
              {filtered ? <button type="button" class="link" onClick={clear}>Clear</button> : null}
              <select id="sort" aria-label="Sort" value={st.sort} onChange={(e) => set({ sort: e.currentTarget.value })}>
                {Object.entries(SORTS).map(([k, [label]]) => <option value={k}>{label}</option>)}
              </select>
            </div>
          </div>

          <dialog ref={sheet} class="sheet" aria-label="Filters" onClick={(e) => e.target === e.currentTarget && e.currentTarget.close()}>
            <div class="sheet-in">
              <div class="sheet-head">
                <h2>Filters</h2>
                <button type="button" class="link" onClick={() => sheet.current?.close()}>Done</button>
              </div>
              {GROUPS.map(([g, title]) => (
                <section>
                  <h3>{title}</h3>
                  {g === "upgrades" ? (
                    <label class="field">
                      I own
                      <select id="from" value={st.from} onChange={(e) => set({ from: e.currentTarget.value })}>
                        <option value="">Pick a ship to see upgrade costs</option>
                        {upgradable.map(([k, name, p, d]) => (
                          <option value={k}>{d ? `${name} ($${(p / 100).toLocaleString("en-US")}, last seen ${new Date(d + "T00:00:00Z").toLocaleDateString("en-US", { month: "short", year: "numeric", timeZone: "UTC" })})` : `${name} (${money(p)})`}</option>
                        ))}
                      </select>
                    </label>
                  ) : null}
                  <div class="chips" role="group" aria-label={title}>
                    {FILTERS.filter((f) => f[3] === g).map(([k, label]) => (
                      <button type="button" class="chip" aria-pressed={st.f.includes(k)} onClick={() => toggle(k)}>
                        {label}{st.view === "store" ? <span class="n">{counts[k]}</span> : null}
                      </button>
                    ))}
                  </div>
                  {g === "sold" ? <p class="muted note">From the Star Citizen Wiki, not RSI: players note which ships only come back for sales. A good guess, not a promise.</p> : null}
                  {g === "game" ? (
                    <label class="field rate" for="rate">
                      I earn
                      <input id="rate" inputMode="numeric" value={rate.toLocaleString("en-US")} onChange={(e) => changeRate(e.currentTarget.value)} />
                      aUEC an hour
                    </label>
                  ) : null}
                  {g === "ship" ? (
                    <div class="selects">
                      <select id="maker" aria-label="Maker" value={st.maker} onChange={(e) => set({ maker: e.currentTarget.value })}>
                        <option value="">All makers</option>
                        {makers.map((m) => <option value={m}>{m}</option>)}
                      </select>
                      <select id="size" aria-label="Size" value={st.size} onChange={(e) => set({ size: e.currentTarget.value })}>
                        <option value="">All sizes</option>
                        {SIZES.map((x) => <option value={x}>{x}</option>)}
                      </select>
                    </div>
                  ) : null}
                </section>
              ))}
              <div class="sheet-foot">
                {filtered ? <button type="button" class="link" onClick={clear}>Clear all</button> : <span />}
                <button type="button" class="show" onClick={() => sheet.current?.close()}>
                  Show {shown.length} {shown.length === 1 ? "ship" : "ships"}
                </button>
              </div>
            </div>
          </dialog>

          {shown.length ? (
            <ul class="ships">{shown.map((s) => <Ship ship={s} now={now} rate={rate} from={st.from} fromName={fromShip?.name} fromPrice={fromPrice} ctx={ctx} pickShip={pickShip} version={data.gameVersion} byValue={st.sort === "value"} />)}</ul>
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
          pledge price history, weapons, gold standard ships and which ships are sale only (the wiki's record, not RSI's) from the <a href="https://starcitizen.tools" target="_blank" rel="noopener">Star Citizen Wiki</a>{" "}
          (<a href="https://creativecommons.org/licenses/by-sa/4.0/" target="_blank" rel="noopener">CC BY-SA 4.0</a>)
          {data.gameVersion ? `, game version ${data.gameVersion}` : ""}. Your aUEC-an-hour figure stays in your browser.
        </p>
        <p>No accounts, no cookies, no tracking. <a href="/privacy">Privacy</a> · <a href="/terms">Terms</a> · <a href="https://github.com/DieLaughing/pledgewatch" target="_blank" rel="noopener">Source on GitHub</a> (AGPL) · <a href="/ships.json">The data as JSON</a>.</p>
      </footer>
    </div>
  );
}

function Ship({ ship: s, now, rate, from, fromName, fromPrice, ctx, pickShip, version, byValue }) {
  const standard = s.editions.find((e) => e.inStore && e.label === "Standard");
  const anchor = s.key.replace(/ /g, "-");
  const [open, setOpen] = useState(() => location.hash === `#${anchor}`);
  useEffect(() => { if (open && location.hash === `#${anchor}`) document.getElementById(anchor)?.scrollIntoView(); }, []);
  const specs = [s.maker, s.role, s.size, s.crew && `crew ${s.crew}`, s.cargo ? `${s.cargo.toLocaleString("en-US")} SCU` : "",
    s.released ? (s.released === "0" ? "in game since the hangar module" : `in game since ${s.released}`) : ""]
    .filter(Boolean).join(" · ");
  const notFlyable = s.status && s.status !== "Flight ready";
  // A rough upgrade cost (target's standard price minus yours) only until RSI's real answer is in.
  const upgrade = ctx.estimate && from && from !== s.key && standard && fromPrice && standard.price > fromPrice ? standard.price - fromPrice : 0;
  const buy = low(s.buy), rent = low(s.rent);
  const sold = SOLD[s.sold];
  return (
    <li id={anchor} class={`ship${s.inStore ? "" : " off"}`}>
      {s.img ? <img src={s.img} alt="" width="160" height="90" loading="lazy" decoding="async" /> : <div class="noimg" />}
      <div class="info">
        <h2>
          {s.rsi ? <a href={s.rsi} target="_blank" rel="noopener">{s.name}</a> : s.name}
          <a class="here" href={`#${anchor}`} aria-label={`Link to ${s.name}`}>#</a>
        </h2>
        <p class="specs">{specs}</p>
        {s.weapons || s.gold || sold ? (
          <p class="arms">
            {sold ? <span class="tag sold" title={`${sold[1]}, ${WIKI_GUESS}.`}>{sold[0]}</span> : null}
            {s.gold ? <span class={`tag ${s.gold.status === "done" ? "gold" : "goldwip"}`} title={goldText(s)}>{s.gold.status === "done" ? "Gold standard" : "Gold pass coming"}</span> : null}
            {s.weapons ? <span>{armsLine(s.weapons)}</span> : null}
          </p>
        ) : null}
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
            <span class="ins">{byValue && value(s) ? `${Math.round(value(s)).toLocaleString("en-US")} aUEC per $` : `≈ ${hours(buy / rate)} of play`}</span>
          </div>
        ) : rent ? (
          <div class="ed ed-game" title="Lowest in-game rental">
            <span class="label">Rent in game</span>
            <span class="price">{auec(rent)}</span>
            <span class="ins">per day</span>
          </div>
        ) : null}
        {!s.inStore && !s.upgrades ? (
          <p class="notin">
            Not in the store
            {s.editions.length ? `, last seen ${ago(Math.max(...s.editions.map((e) => e.lastSeen)), now)}` : ""}
          </p>
        ) : null}
      </div>
      <Upgrades s={s} from={from} fromName={fromName} costs={ctx.costs} pickShip={pickShip} plan={s.ccu ? planLink(s.name, ctx.costs ? fromName : "") : ""} />
      {open ? <Details s={s} rate={rate} version={version} /> : null}
    </li>
  );
}

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const MOUNT = {
  hardpoints: "Hardpoints", manned: "crewed turret", remote: "remote turret", pdc: "point-defence turret",
  "manned-missile": "crewed missile turret", "remote-missile": "remote missile turret",
};
const WHO = [["pilot", "Pilot"], ["both", "Pilot or gunner"], ["gunner", "Gunners"], ["auto", "Automatic"]];
const MISSILE = { missile: ["missile", "missiles"], torpedo: ["torpedo", "torpedoes"], bomb: ["bomb", "bombs"] };
const num = (n) => (n ? n.toLocaleString("en-US") : "–");
// The three damage figures as one line, for narrow screens where they don't fit as columns.
const Stats = ({ d }) => (d[0] ? <span class="stats-inline"><b>{num(d[0])}</b> DPS · <b>{num(d[1])}</b> sustained · <b>{num(d[2])}</b> alpha</span> : null);

// Card summary, e.g. "Pilot: 2× S4 + 2 turrets · Gunners: 2 turrets · 7 PDCs".
function armsLine(w) {
  const own = w.guns.find((r) => r[0] === "pilot");
  const sizes = {};
  for (const [n, size] of own ? own[3] : []) sizes[size] = (sizes[size] || 0) + n;
  const guns = Object.entries(sizes).sort((a, b) => b[0] - a[0]).map(([size, n]) => `${n}× S${size}`).join(", ");
  const count = (who) => w.guns.filter((r) => r[0] === who).reduce((a, r) => a + r[2], 0);
  const pilot = [guns, count("both") && plural(count("both"), "turret")].filter(Boolean).join(" + ");
  const gunners = count("gunner"), pdc = count("auto");
  return [`Pilot: ${pilot || "no guns"}`, gunners && `Gunners: ${plural(gunners, "turret")}`, pdc && plural(pdc, "PDC")].filter(Boolean).join(" · ");
}

function goldText(s) {
  const g = s.gold, of = g.family ? ` (the ${g.family} family)` : "";
  return g.status === "done"
    ? `Gold standard pass${of}${g.patch ? ` in ${g.patch}` : ""}: reworked to every ship feature the game has so far`
    : `Gold standard pass${of} in progress`;
}

function hours(h) {
  if (h < 1) return `${Math.max(5, Math.round(h * 60 / 5) * 5)} min`;
  return h < 10 ? `${+h.toFixed(1)} h` : `${Math.round(h)} h`;
}

function Details({ s, rate, version }) {
  const dollars = pledgeDollars(s);
  const buy = low(s.buy), rent = low(s.rent);
  const history = s.history || [];
  const wb = history.filter((h) => h[2]);
  const lowestWb = wb.length ? wb.reduce((a, b) => (b[1] < a[1] ? b : a)) : null;
  const lastWb = wb.length ? wb[wb.length - 1] : null;
  const std = history.filter((h) => !h[2] && h[3] === "store");
  const lastStd = std.length ? std[std.length - 1] : null;
  const [all, setAll] = useState(false);
  const rows = [...history].reverse();
  const shownRows = all ? rows : rows.slice(0, 8);
  const month = (d) => new Date(d + "T00:00:00Z").toLocaleDateString("en-US", { month: "short", year: "numeric", timeZone: "UTC" });
  const storeIns = s.editions.filter((e) => e.inStore && e.insurance);
  const w = s.weapons;
  return (
    <div class="details">
      <section>
        <h3>In game</h3>
        {s.gold ? <p class={`gold-note ${s.gold.status === "done" ? "done" : ""}`}>{goldText(s)}.</p> : null}
        {buy ? (
          <dl class="facts">
            <dt>Buy</dt><dd><b>{auec(buy)}</b> at {s.buy.find((x) => x[0] === buy)[1]}</dd>
            <dt>Your time</dt><dd>about <b>{hours(buy / rate)}</b> at {auec(rate)} an hour</dd>
            {dollars ? <><dt>Value</dt><dd>{Math.round(buy / dollars).toLocaleString("en-US")} aUEC per pledge dollar (${dollars.toLocaleString("en-US")})</dd></> : null}
            {rent ? <Rent list={s.rent} /> : null}
          </dl>
        ) : rent ? (
          <dl class="facts">
            <dt>Buy</dt><dd class="muted">Not sold in game right now</dd>
            <Rent list={s.rent} />
          </dl>
        ) : (
          <p class="muted">Not sold or rented in game right now. New ships usually reach the pledge store long before they're sold in game.</p>
        )}
        {s.buy && s.buy.length > 1 ? (
          <ul class="where">{s.buy.map(([p, t]) => <li><span>{t}</span><span>{auec(p)}</span></li>)}</ul>
        ) : null}
      </section>

      <section>
        <h3>Insurance</h3>
        <dl class="facts">
          {s.insurance ? (
            <>
              <dt>Claim</dt><dd><b>{s.insurance.claim} min</b></dd>
              <dt>Expedite</dt><dd><b>{s.insurance.expedite} min</b> for {s.insurance.expediteCost.toLocaleString("en-US")} aUEC</dd>
            </>
          ) : <><dt>Claim</dt><dd class="muted">No times known yet</dd></>}
          {storeIns.length ? <><dt>From the store</dt><dd>{storeIns.map((e) => `${e.label}: ${e.insurance === "Lifetime" ? "lifetime" : e.insurance}`).join(" · ")}</dd></> : null}
          {s.loaners ? <><dt>Loaners</dt><dd>{s.loaners}</dd></> : null}
        </dl>
        {version && s.insurance ? <p class="muted small">Claim times from game version {version}.</p> : null}
      </section>

      {w ? (
        <section class="wide">
          <h3>Weapons</h3>
          {w.guns.length ? <Arms w={w} /> : <p class="muted">No guns or missile turrets.</p>}
          {w.missiles.length ? (
            <dl class="facts arms-facts">
              <dt>Missiles</dt>
              <dd>{w.missiles.map(([n, size, kind]) => `${n}× S${size} ${MISSILE[kind][n === 1 ? 0 : 1]}`).join(" · ")}</dd>
            </dl>
          ) : null}
          <p class="muted small">
            <b>DPS</b> is damage a second while firing, <b>sustained</b> is the average once heat and reloads catch up,
            and <b>alpha</b> is one volley from every gun on the line. Stock loadout{version ? ` in game version ${version}` : ""},
            from the Star Citizen Wiki.
          </p>
        </section>
      ) : null}

      {history.length ? (
        <section class="wide">
          <h3>Price history</h3>
          {SOLD[s.sold] ? <p class="muted small sold-note">{SOLD[s.sold][1]}, {WIKI_GUESS}.</p> : null}
          <div class="stats">
            {lastStd ? <div><span>Standard now</span><b>${lastStd[1].toLocaleString("en-US")}</b></div> : null}
            <div><span>Lowest warbond</span><b>{lowestWb ? `$${lowestWb[1].toLocaleString("en-US")}` : "never seen"}</b>{lowestWb ? <i>{month(lowestWb[0])}</i> : null}</div>
            {lastWb ? <div><span>Last warbond</span><b>${lastWb[1].toLocaleString("en-US")}</b><i>{month(lastWb[0])}</i></div> : null}
          </div>
          <div class="table-wrap">
            <table class="hist">
              <thead><tr><th>Seen</th><th>Edition</th><th>Where</th><th class="num">Price</th></tr></thead>
              <tbody>
                {shownRows.map(([d, p, w, src]) => (
                  <tr>
                    <td>{month(d)}</td>
                    <td class={w ? "wb" : ""}>{w ? "Warbond" : "Standard"}</td>
                    <td class="muted">{src === "upgrade" ? "Upgrade store" : "Pledge store"}</td>
                    <td class="num">${p.toLocaleString("en-US")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {rows.length > 8 ? <button type="button" class="link" onClick={() => setAll(!all)}>{all ? "Show fewer" : `Show all ${rows.length}`}</button> : null}
          <p class="muted small">Upgrade store prices are what the ship is worth as a CCU target, which can differ from buying it outright.</p>
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

// The cheapest place to rent, with every other place one tap away: some ships rent at 30 places, too many to show.
// Opened, places are grouped by price (most charge the same), so the list stays a few lines even on a phone.
function Rent({ list }) {
  const [open, setOpen] = useState(false);
  const best = low(list);
  const byPrice = {};  // by the price as shown: a few aUEC apart reads as the same price
  for (const [p, t] of [...list].sort((a, b) => a[0] - b[0])) (byPrice[auec(p)] ||= []).push(t);
  return (
    <>
      <dt>Rent</dt>
      <dd>
        <b>{auec(best)}</b> a day at {list.find((x) => x[0] === best)[1]}
        {list.length > 1 ? <>{" · "}<button type="button" class="link" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "hide places" : `all ${list.length} places`}</button></> : null}
      </dd>
      {open ? (
        <dd class="places">
          <ul>
            {Object.entries(byPrice).map(([p, places]) => (
              <li><b>{p}</b>{places.length > 1 ? ` at ${places.length} places` : ""}: {places.sort().join(", ")}</li>
            ))}
          </ul>
        </dd>
      ) : null}
    </>
  );
}

// Every gun and missile turret, grouped by who fires it, with the damage of each line and totals.
function Arms({ w }) {
  const all = [0, 1, 2].map((i) => w.guns.reduce((a, r) => a + r[4 + i], 0));
  const crewed = w.guns.some((r) => (r[0] === "gunner" || r[0] === "auto") && r[4]);
  return (
    <div class="table-wrap">
      <table class="loadout">
        <thead>
          <tr>
            <th class="mount">Mount</th><th>Guns</th>
            <th class="num">DPS</th><th class="num">Sustained</th><th class="num">Alpha</th>
          </tr>
        </thead>
        {WHO.map(([who, label]) => {
          const rows = w.guns.filter((r) => r[0] === who);
          return rows.length ? (
            <tbody>
              <tr class="group"><th colspan="5" scope="rowgroup">{label}</th></tr>
              {rows.map(([, mount, n, each, dps, sus, alpha]) => {
                const where = mount === "hardpoints" ? MOUNT[mount] : plural(n, MOUNT[mount]);
                return (
                  <tr>
                    <td class="mount">{where}</td>
                    <td class="guns">
                      <span class="mount-inline">{where}</span>
                      {each.map(([c, size, name]) => <div><b>{c}×</b> {size ? `S${size} ` : ""}{name}</div>)}
                      {n > 1 && mount !== "hardpoints" ? <span class="each">on each turret</span> : null}
                      <Stats d={[dps, sus, alpha]} />
                    </td>
                    <td class="num">{num(dps)}</td><td class="num">{num(sus)}</td><td class="num">{num(alpha)}</td>
                  </tr>
                );
              })}
            </tbody>
          ) : null;
        })}
        <tfoot>
          <tr>
            <th colspan="2" scope="row">Pilot alone<Stats d={w.pilot} /></th>
            <td class="num">{num(w.pilot[0])}</td><td class="num">{num(w.pilot[1])}</td><td class="num">{num(w.pilot[2])}</td>
          </tr>
          {crewed ? (
            <tr>
              <th colspan="2" scope="row">Fully crewed<Stats d={all} /></th>
              <td class="num">{num(all[0])}</td><td class="num">{num(all[1])}</td><td class="num">{num(all[2])}</td>
            </tr>
          ) : null}
        </tfoot>
      </table>
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
      {upgrade ? <span class="up" title="Rough estimate: RSI's real upgrade cost couldn't be checked">≈ upgrade +{money(upgrade)}</span> : null}
      {state ? <span class="state">{state}</span> : null}
    </a>
  );
}

// The upgrades (CCUs) to this ship on sale now. An upgrade's price is the ship's value as an upgrade target: you pay it
// minus the value of the ship you upgrade from. With a ship picked under "I own" and RSI's answer in, show exactly what
// each upgrade that ship can take costs from it.
function Upgrades({ s, from, fromName, costs, pickShip, plan }) {
  const [why, setWhy] = useState(false);
  const list = s.upgrades || [];
  if (!list.length || from === s.key) return null;
  const value = s.ccu?.value || 0;
  const tool = <a class="tool" href={CCU_TOOL} target="_blank" rel="noopener">Buy in your RSI hangar ↗</a>;
  const route = plan ? <a class="link mine" href={plan}>Plan a route</a> : null;
  if (from && costs) {
    const mine = list.filter((u) => u.sku in costs).sort((a, b) => costs[a.sku] - costs[b.sku]);
    if (!mine.length) {
      return <p class="ccu muted">Upgrades to it are on sale ({list.map((u) => u.label).join(", ")}), but none apply from your {fromName}{route ? <> · {route}</> : null}</p>;
    }
    return (
      <p class="ccu">
        <span class="k">You pay from your {fromName}</span>
        {mine.map((u) => <span class={`u${u.price < value ? " deal" : ""}`}><b>{money(costs[u.sku])}</b> {u.label}</span>)}
        {tool}
        {route}
      </p>
    );
  }
  const low = list.find((u) => !/upgrade$/i.test(u.label)) || list[0];  // a regular edition makes the clearer example
  return (
    <div class="ccu">
      <span class="k">
        Upgrade value
        <button type="button" class="why" aria-expanded={why} aria-label="What's an upgrade value?" onClick={() => setWhy(!why)}>?</button>
      </span>
      {list.map((u) => (
        <span class={`u${u.price < value ? " deal" : ""}`}>
          {u.label} <b>{money(u.price)}</b>{u.price < value ? ` (saves ${money(value - u.price)})` : ""}
        </span>
      ))}
      <button type="button" class="link mine" onClick={pickShip}>What would I pay?</button>
      {route}
      {why ? (
        <p class="explain">
          An upgrade (CCU) turns a ship you already own into this one. You pay the upgrade value minus your ship's value:
          {low.price > 10000 ? ` from a $100 ship, the ${low.label}${/upgrade$/i.test(low.label) ? "" : " upgrade"} costs ${money(low.price - 10000)}.` : " the difference."}{" "}
          Upgrades aren't sold on the ship's store page: you buy them from your RSI hangar (My Hangar, Ship Upgrade) while logged in, where "ship value" is this same number. Warbond and one-off
          upgrades often only work from certain ships, so pick yours to see what really applies. {tool}
        </p>
      ) : null}
    </div>
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
