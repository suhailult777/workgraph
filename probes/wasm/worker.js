import init, { RelateDb } from "./node_modules/@relate/relate-wasm/relate.js";

let db;

self.onmessage = async (e) => {
  try {
    const cmd = e.data.cmd;
    if (cmd === "open") {
      await init();
      db = await RelateDb.open("opfs://workgraph-probe");
      const r = JSON.parse(db.execute("MATCH (n) RETURN count(n) AS n", null));
      db.execute("CREATE (:Probe {at: $at})", JSON.stringify({ at: new Date().toISOString() }));
      const after = JSON.parse(db.execute("MATCH (n) RETURN count(n) AS n", null));
      db.free();
      db = null;
      self.postMessage({ ok: true, before: r.rows[0].n, after: after.rows[0].n, durable: true });
      return;
    }
    if (cmd === "read") {
      await init();
      db = await RelateDb.open("opfs://workgraph-probe");
      const r = JSON.parse(db.execute("MATCH (n) RETURN count(n) AS n", null));
      db.free();
      db = null;
      self.postMessage({ ok: true, count: r.rows[0].n, durable: true });
      return;
    }
    self.postMessage({ ok: false, error: "unknown command" });
  } catch (err) {
    self.postMessage({ ok: false, error: String(err) });
  }
};
