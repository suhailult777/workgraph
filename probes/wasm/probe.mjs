import { readFile } from "node:fs/promises";
import init, { RelateDb } from "@relate/relate-wasm";

const wasm = await readFile(new URL("./node_modules/@relate/relate-wasm/relate_bg.wasm", import.meta.url));
await init(wasm);

const db = new RelateDb();
const run = (q, p = null) => JSON.parse(db.execute(q, p ? JSON.stringify(p) : null));

console.log("version statement:", JSON.stringify(run("RETURN 1 AS ok")));
console.log("write:", JSON.stringify(run("CREATE (:Probe {name: $name})", { name: "wasm" })));
console.log("read:", JSON.stringify(run("MATCH (p:Probe) RETURN p.name AS name")));
console.log("multi-hop:", JSON.stringify(run(
  "CREATE (:A {id: 1})-[:NEXT]->(:B {id: 2})-[:NEXT]->(:C {id: 3})"
)));
console.log("path:", JSON.stringify(run(
  "MATCH (a:A)-[:NEXT*2]->(c:C) RETURN a.id AS from, c.id AS to"
)));
db.free();
