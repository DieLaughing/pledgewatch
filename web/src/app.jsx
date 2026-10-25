import { useEffect, useMemo, useState } from "preact/hooks";

const FILTERS = [
  ["warbond", "Warbond", (s) => s.editions.some((e) => e.inStore && e.label === "Warbond")],
  ["anniversary", "10 Year", (s) => s.editions.some((e) => e.inStore && e.label === "10 Year")],
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
};
const KIND = {
  new: ["Came in", "good"], back: ["Back", "good"], restock: ["Restocked", "good"], low: ["Low stock", "warn"],
  sold_out: ["Sold out", "bad"], gone: ["Left the store", "bad"], price: ["Price", "info"],
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
            </div>
          </div>

          <p class="count">
            {shown.length} {shown.length === 1 ? "ship" : "ships"}
            {filtered ? <button type="button" class="link" onClick={clear}>Clear filters</button> : null}
          </p>

          {shown.length ? (
            <ul class="ships">{shown.map((s) => <Ship ship={s} now={now} />)}</ul>
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
          minutes. Ship details from RSI's Ship Matrix and Loaner Ship Matrix.
        </p>
        <p>No accounts, no cookies, no tracking. <a href="/ships.json">The data as JSON</a>.</p>
      </footer>
    </div>
  );
}

function Ship({ ship: s, now }) {
  const standard = s.editions.find((e) => e.inStore && e.label === "Standard");
  const specs = [s.maker, s.role, s.size, s.crew && `crew ${s.crew}`].filter(Boolean).join(" · ");
  const notFlyable = s.status && s.status !== "Flight ready";
  return (
    <li class={`ship${s.inStore ? "" : " off"}`}>
      {s.img ? <img src={s.img} alt="" width="160" height="90" loading="lazy" decoding="async" /> : <div class="noimg" />}
      <div class="info">
        <h2>{s.rsi ? <a href={s.rsi} target="_blank" rel="noopener">{s.name}</a> : s.name}</h2>
        <p class="specs">{specs}</p>
        {notFlyable ? (
          <p class="status">
            <span class="tag concept">{s.status}</span>
            {s.loaners ? ` Loaners: ${s.loaners}` : ""}
          </p>
        ) : null}
      </div>
      <div class="buy">
        {s.editions.filter((e) => e.inStore).map((e) => <Edition e={e} standard={standard} />)}
        {!s.inStore ? (
          <p class="notin">
            Not in the store
            {s.editions.length ? `, last seen ${ago(Math.max(...s.editions.map((e) => e.lastSeen)), now)}` : ""}
          </p>
        ) : null}
      </div>
    </li>
  );
}

function Edition({ e, standard }) {
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
      {saving ? <span class="save">save {money(saving)}</span> : null}
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
            <a href={c.url} target="_blank" rel="noopener">{c.name}</a>
            <span class="amt">
              {c.kind === "price" && c.was ? <s>{money(c.was)}</s> : null}
              {money(c.price)}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
