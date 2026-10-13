const test = require("node:test");
const assert = require("node:assert");
const { add } = require("./calcx.js");

test("add", () => {
  assert.strictEqual(add(2, 3), 5);
});
