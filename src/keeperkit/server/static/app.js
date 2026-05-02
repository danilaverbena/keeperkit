async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body || {}),
  });
  return await res.json();
}

function renderResult(el, result, ok) {
  el.classList.remove("ok", "err");
  el.classList.add(ok ? "ok" : "err");
  el.textContent = JSON.stringify(result, null, 2);
}

document.querySelectorAll(".example").forEach((b) => {
  b.addEventListener("click", () => {
    document.getElementById("prompt").value = b.dataset.prompt;
    document.getElementById("prompt").focus();
  });
});

document.getElementById("run").addEventListener("click", async () => {
  const prompt = document.getElementById("prompt").value.trim();
  const useMock = document.getElementById("forceMock").checked;
  const out = document.getElementById("agent-out");
  if (!prompt) { out.textContent = "Type a prompt first."; return; }
  out.classList.remove("ok", "err");
  out.textContent = "running…";
  const result = await postJSON("/api/agent/run",
    {prompt, use_mock: useMock || null});
  renderResult(out, result, result.ok);
});

// Each tool details block has its own dispatcher.
document.querySelectorAll(".tool").forEach((tool) => {
  const name = tool.dataset.name;
  const args = tool.querySelector(".tool-args");
  const out = tool.querySelector(".tool-out");
  const run = tool.querySelector(".tool-run");

  // Replace the schema preview with a sensible empty argument template the
  // first time the user opens the tool body.
  let prefilled = false;
  tool.addEventListener("toggle", () => {
    if (tool.open && !prefilled) {
      try {
        const schema = JSON.parse(args.value);
        const props = schema.properties || {};
        const example = {};
        for (const k of Object.keys(props)) {
          const t = props[k].type || "string";
          example[k] =
            t === "integer" || t === "number" ? 0 :
            t === "boolean" ? false :
            t === "array" ? [] :
            t === "object" ? {} : "";
        }
        args.value = JSON.stringify(example, null, 2);
      } catch (_e) { /* leave the schema as-is */ }
      prefilled = true;
    }
  });

  run.addEventListener("click", async () => {
    let parsed;
    try { parsed = JSON.parse(args.value || "{}"); }
    catch (e) { renderResult(out, {error: "Invalid JSON: " + e.message}, false); return; }
    out.classList.remove("ok", "err");
    out.textContent = "calling " + name + "…";
    const result = await postJSON("/api/tools/" + name, {arguments: parsed});
    renderResult(out, result, result.ok !== false);
  });
});
