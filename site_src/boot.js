// StockGuard in the browser: the same Python package, run by Pyodide (SPEC UC-8). No server, no key, no wallet.
// The page calls window.stockguardApi("/api/check?...") instead of fetch(); the answer comes from
// stockguard.adapters.browser.BrowserApp, which reads the Binance public endpoints from this browser.
(function () {
  const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.27.7/full/";
  const say = (t) => { const m = document.getElementById("mode"); if (m) m.textContent = t; };
  let ready = null;
  function boot() {
    if (ready) return ready;
    ready = new Promise((resolve, reject) => {
      say("Loading the checker into your browser (first visit takes a few seconds)…");
      const s = document.createElement("script");
      s.src = PYODIDE + "pyodide.js";
      s.onerror = () => reject(new Error("Could not load Pyodide from " + PYODIDE));
      s.onload = async () => {
        try {
          const py = await loadPyodide({ indexURL: PYODIDE });
          const zip = await (await fetch("stockguard.zip")).arrayBuffer();
          py.unpackArchive(zip, "zip", { extractDir: "/home/pyodide/sg" });
          py.runPython(`
import sys
sys.path.insert(0, "/home/pyodide/sg")
from stockguard.adapters.browser import BrowserApp, pyodide_io
app = BrowserApp(*pyodide_io())
`);
          say("Running in your browser on live Binance Web3 data. The token-audit API does not accept browser requests, " +
              "so the agent line treats the audit as unreachable (the CLI calls it).");
          resolve(py);
        } catch (e) { reject(e); }
      };
      document.head.appendChild(s);
    });
    return ready;
  }
  window.stockguardApi = async (url) => {
    const py = await boot();
    const [status, body] = JSON.parse(py.globals.get("app").handle(url));
    return { status, ok: status >= 200 && status < 300, json: async () => body };
  };
  boot().catch((e) => say("Could not start the in-browser checker: " + e.message));
})();
