// Stack Analyzer — client. Builds every node with createElement + textContent:
// nothing from the server or the user is ever parsed as HTML.
"use strict";

(() => {
  const form = document.getElementById("stack-form");
  const input = document.getElementById("stack");
  const help = document.getElementById("stack-help");
  const submit = document.getElementById("submit");
  const label = submit.querySelector(".btn__label");
  const clear = document.getElementById("clear");
  const results = document.getElementById("results");
  const formError = document.getElementById("form-error");
  const emptyState = results.firstElementChild.cloneNode(true);
  const HELP_TEXT = help.textContent;
  const chips = document.querySelectorAll("[data-example]");
  const CITATION_HOSTS = new Set(["api.fda.gov", "ods.od.nih.gov"]);
  const KIND_LABEL = {
    interaction: "Interaction",
    redundancy: "Duplicate",
    upper_limit: "Upper limit",
    timing: "Timing",
    unresolved: "Incomplete check",
  };

  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  // Defence in depth: the server already filters URLs; the client checks again.
  const safeUrl = (value) => {
    if (typeof value !== "string") return null;
    try {
      const url = new URL(value);
      if (url.protocol !== "https:" || !CITATION_HOSTS.has(url.hostname)) return null;
      if (url.username || url.password || url.port) return null;
      return url.href;
    } catch {
      return null;
    }
  };

  const setFieldError = (message) => {
    if (message) {
      input.setAttribute("aria-invalid", "true");
      help.textContent = message;
      help.classList.add("is-error");
    } else {
      input.removeAttribute("aria-invalid");
      help.textContent = HELP_TEXT;
      help.classList.remove("is-error");
    }
  };

  const setFormError = (message) => {
    formError.replaceChildren();
    if (!message) {
      formError.hidden = true;
      return;
    }
    formError.append(el("strong", null, "Check didn’t run. "), document.createTextNode(message));
    formError.hidden = false;
  };

  // Spinner shows only if the request outlasts 150 ms, so fast answers don't flash.
  let busyTimer = null;
  const setBusy = (busy) => {
    clearTimeout(busyTimer);
    results.setAttribute("aria-busy", String(busy));
    for (const chip of chips) chip.disabled = busy;
    if (busy) {
      submit.disabled = true;
      busyTimer = setTimeout(() => {
        submit.setAttribute("aria-busy", "true");
        label.textContent = "Checking…";
      }, 150);
    } else {
      submit.disabled = false;
      submit.removeAttribute("aria-busy");
      label.textContent = "Check stack";
    }
  };

  // One disclosure per finding, however many labels say the same thing.
  const renderCitations = (citations) => {
    const details = el("details", "cite");
    const labels = [...new Set(citations.map((c) => c.label))].join(" and ");
    const count = citations.length === 1 ? "" : ` (${citations.length})`;
    details.append(el("summary", "cite__summary", `Source: ${labels}${count}`));
    for (const citation of citations) {
      const body = el("div", "cite__body");
      body.append(el("p", "cite__quote", `“${citation.quote}”`));
      const href = safeUrl(citation.url);
      if (href) {
        const link = el("a", "cite__link", `Open ${citation.label} ↗`);
        link.href = href;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        body.append(link);
      }
      details.append(body);
    }
    return details;
  };

  const renderReport = (data) => {
    const frag = document.createDocumentFragment();
    let i = 0;
    const reveal = (node) => {
      node.classList.add("is-revealed");
      node.style.setProperty("--i", String(Math.min(i++, 6)));
      return node;
    };

    const head = reveal(el("div", "report__head"));
    head.append(el("h2", "report__summary", data.summary));
    const counts = [`${data.identified} identified`];
    if (data.unidentified.length) counts.push(`${data.unidentified.length} not checked`);
    counts.push(`${data.findings.length} finding${data.findings.length === 1 ? "" : "s"}`);
    head.append(el("p", "report__counts", counts.join(" · ")));
    frag.append(head);

    if (data.findings.length) {
      const list = el("ol", "findings");
      for (const f of data.findings) {
        const item = reveal(el("li", "finding"));
        const meta = el("div", "finding__meta");
        meta.append(
          el("span", `sev sev--${f.severity}`, f.severity),
          el("span", "finding__kind", KIND_LABEL[f.kind] || "Finding"),
        );
        item.append(meta, el("h3", "finding__title", f.title), el("p", "finding__detail", f.detail));
        if (f.citations.length) item.append(renderCitations(f.citations));
        list.append(item);
      }
      frag.append(list);
    }

    if (data.unidentified.length) {
      const block = reveal(el("div", "notchecked"));
      block.append(el("h3", "notchecked__title", "Not checked"));
      const ul = el("ul", "notchecked__list");
      for (const name of data.unidentified) ul.append(el("li", null, name));
      block.append(
        ul,
        el(
          "p",
          "notchecked__text",
          "These aren’t in the database yet, or the name is too general to match one compound (“B complex”, “multivitamin”). Check the spelling, or list the individual ingredients. Anything not checked could still interact.",
        ),
      );
      frag.append(block);
    }

    frag.append(reveal(el("p", "disclaimer", data.disclaimer)));
    results.replaceChildren(frag);

    // On one-column layouts the report lands below the fold; bring it into view
    // so a tap on "Check stack" visibly does something.
    const top = results.getBoundingClientRect().top;
    if (top > window.innerHeight * 0.6) {
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      results.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
    }
  };

  const run = async () => {
    setFormError(null);
    const text = input.value.trim();
    if (!text) {
      setFieldError("Add at least one supplement or medication to check.");
      input.focus();
      return;
    }
    setFieldError(null);
    setBusy(true);
    try {
      const response = await fetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
        credentials: "same-origin",
      });
      let data = null;
      try {
        data = await response.json();
      } catch {
        data = null;
      }
      if (!response.ok || !data || data.error) {
        const message = (data && typeof data.error === "string" && data.error) ||
          "The server didn’t answer as expected. Try again in a moment.";
        if (response.status === 413 || response.status === 422) setFieldError(message);
        else setFormError(message);
        return;
      }
      renderReport(data);
    } catch {
      setFormError("The request didn’t reach the server. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  };

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    run();
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      run();
    }
  });

  input.addEventListener("input", () => {
    if (input.getAttribute("aria-invalid") === "true" && input.value.trim()) setFieldError(null);
  });

  clear.addEventListener("click", () => {
    input.value = "";
    setFieldError(null);
    setFormError(null);
    results.replaceChildren(emptyState.cloneNode(true));
    input.focus();
  });

  for (const chip of chips) {
    chip.addEventListener("click", () => {
      input.value = chip.dataset.example;
      setFieldError(null);
      run();
    });
  }
})();
