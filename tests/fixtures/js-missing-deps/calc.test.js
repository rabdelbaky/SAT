const test = require("node:test");
const assert = require("node:assert");
const leftPad = require("left-pad");

test("pad", () => {
  assert.strictEqual(leftPad("1", 2, "0"), "01");
});
