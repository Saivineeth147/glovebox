// Perception walker: runs inside one frame and returns every perceivable element with the
// properties a human operator would use to identify it. Deliberately avoids ids/test-ids
// (legacy apps have none) and computes labels from table-layout adjacency.
(() => {
  const INTERACTIVE = new Set(["a", "button", "input", "select", "textarea"]);
  const out = [];
  const vw = window.innerWidth || 1, vh = window.innerHeight || 1;

  function visible(el) {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    const s = getComputedStyle(el);
    return s.visibility !== "hidden" && s.display !== "none" && s.opacity !== "0";
  }
  function cssPath(el) {
    const parts = [];
    while (el && el.nodeType === 1 && el.tagName.toLowerCase() !== "html") {
      let sel = el.tagName.toLowerCase();
      const parent = el.parentElement;
      if (parent) {
        const sibs = Array.from(parent.children).filter(c => c.tagName === el.tagName);
        if (sibs.length > 1) sel += `:nth-of-type(${sibs.indexOf(el) + 1})`;
      }
      parts.unshift(sel);
      el = parent;
    }
    return parts.join(" > ");
  }
  function ownText(el) {
    return (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 200);
  }
  function labelFor(el) {
    if (el.id) { const l = document.querySelector(`label[for="${el.id}"]`); if (l) return ownText(l); }
    const wrap = el.closest("label"); if (wrap) return ownText(wrap).replace(ownText(el), "").trim();
    const aria = el.getAttribute("aria-label"); if (aria) return aria;
    // legacy table forms: the label is the previous cell in the same row
    const td = el.closest("td,th");
    if (td) {
      let prev = td.previousElementSibling;
      while (prev && !ownText(prev)) prev = prev.previousElementSibling;
      if (prev && ownText(prev)) return ownText(prev);
    }
    // otherwise the nearest preceding text node
    let n = el.previousSibling;
    while (n) { const t = (n.textContent || "").trim(); if (t) return t.slice(0, 80); n = n.previousSibling; }
    return null;
  }
  function roleOf(el) {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute("type") || "").toLowerCase();
    const explicit = el.getAttribute("role"); if (explicit) return explicit;
    if (tag === "a") return el.hasAttribute("href") ? "link" : "text";
    if (tag === "button") return "button";
    if (tag === "input") {
      if (["submit", "button", "reset", "image"].includes(type)) return "button";
      if (type === "checkbox") return "checkbox";
      if (type === "radio") return "radio";
      return "textbox";
    }
    if (tag === "select") return "combobox";
    if (tag === "textarea") return "textbox";
    if (/^h[1-6]$/.test(tag)) return "heading";
    if (tag === "td" || tag === "th") return "cell";
    return "text";
  }
  function nameOf(el, role) {
    const tag = el.tagName.toLowerCase();
    if (tag === "input") {
      const type = (el.getAttribute("type") || "").toLowerCase();
      if (["submit", "button", "reset"].includes(type)) return el.value || type;
      return el.getAttribute("aria-label") || el.getAttribute("placeholder") || labelFor(el) || el.getAttribute("name") || "";
    }
    if (tag === "select" || tag === "textarea") return el.getAttribute("aria-label") || labelFor(el) || el.getAttribute("name") || "";
    return ownText(el);
  }

  const all = document.querySelectorAll("a,button,input,select,textarea,h1,h2,h3,h4,td,th,b,p,div.notice,div.err,span,font,li");
  let i = 0;
  for (const el of all) {
    if (!visible(el)) continue;
    const tag = el.tagName.toLowerCase();
    const interactive = INTERACTIVE.has(tag) && !el.disabled && !(tag === "input" && el.type === "hidden");
    const role = roleOf(el);
    // Non-interactive: only keep leaf-ish text carriers to keep the tree compact.
    if (!interactive) {
      if (tag === "td" || tag === "th") {
        if (el.querySelector("table") || !ownText(el)) continue;
      } else if (["span", "font", "b", "p", "li", "div"].includes(tag)) {
        if (el.querySelector("a,button,input,select,table") || !ownText(el)) continue;
      } else if (!ownText(el)) continue;
    }
    const r = el.getBoundingClientRect();
    const options = tag === "select" ? Array.from(el.options).map(o => o.text.trim()) : [];
    let table = null, row = -1, col = -1;
    if (tag === "td" || tag === "th") {
      const tr = el.parentElement, tbl = el.closest("table");
      if (tr && tbl) { table = cssPath(tbl); row = Array.from(tbl.rows).indexOf(tr); col = Array.from(tr.cells).indexOf(el); }
    }
    out.push({
      idx: i++, tag, role, interactive,
      name: nameOf(el, role).slice(0, 120),
      text: ownText(el),
      label: interactive ? labelFor(el) : null,
      name_attr: el.getAttribute("name") || null,
      value: (tag === "input" && el.type === "password") ? (el.value ? "••••" : "") : (tag === "input" || tag === "select" || tag === "textarea") ? (el.value || "") : null,
      href: tag === "a" ? el.getAttribute("href") : null,
      options,
      css: cssPath(el),
      table, row, col,
      bbox: [r.left, r.top, r.width, r.height],
      nbox: [(r.left + r.width / 2) / vw, (r.top + r.height / 2) / vh],
    });
  }
  const text = (document.body ? (document.body.innerText || "") : "").replace(/[ \t]+/g, " ").replace(/\n{2,}/g, "\n").trim();
  return { elements: out, text: text.slice(0, 6000), title: document.title, url: location.href };
})()
