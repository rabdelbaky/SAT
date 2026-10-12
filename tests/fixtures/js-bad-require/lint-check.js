// Stdlib "linter" for the js-* fixtures: no `debugger` statements in *.js files.
// Exit 1 and print each offence. Writes no files.
const fs = require("node:fs");
let failed = false;
for (const f of fs.readdirSync(".").filter((n) => n.endsWith(".js") && n !== "lint-check.js").sort()) {
  fs.readFileSync(f, "utf8").split("\n").forEach((line, i) => {
    if (/\bdebugger\b/.test(line)) {
      console.log(`${f}:${i + 1}: no-debugger`);
      failed = true;
    }
  });
}
process.exit(failed ? 1 : 0);
