import { test } from "node:test";
import assert from "node:assert/strict";
import {
  parseTrajectory,
  nearest,
  sampled,
  metric,
  eventLabel,
} from "./data.ts";
test("bounded numeric evidence rejects malformed, nonfinite and unordered input", () => {
  for (const value of [
    "<svg onload=alert(1)>",
    "t,x\n0,1\n1,NaN",
    "t,x\n0,1\n0,2",
    "t,x\n0,1\n6,0",
    "t,x\n0,1\n1,Infinity",
    "t,x\n0,1\n1,1e9",
  ])
    assert.throws(() => parseTrajectory(value));
  assert.deepEqual(parseTrajectory("t,x\r\n0,1\r\n1,0.5\r\n"), [
    { t: 0, x: 1 },
    { t: 1, x: 0.5 },
  ]);
});
test("plot sampling preserves endpoint and nearest readout uses raw data", () => {
  const points = Array.from({ length: 20000 }, (_, i) => ({
    t: i / 4000,
    x: i,
  }));
  const out = sampled(points);
  assert.ok(out.length <= 801);
  assert.equal(out.at(-1), points.at(-1));
  assert.equal(nearest(points, 1)?.x, 4000);
  assert.equal(metric(NaN), "—");
  assert.equal(eventLabel("TOOL", { tool: "get_job" }), null);
});
