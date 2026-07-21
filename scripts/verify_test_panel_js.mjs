import fs from "node:fs";

const html = fs.readFileSync("app/test_panel.html", "utf8");
const scriptStart = html.indexOf("<script>") + "<script>".length;
const scriptEnd = html.lastIndexOf("</script>");
const panelScript = html.slice(scriptStart, scriptEnd);
const testableScript = panelScript.replace(
  /initialize\(\)\.catch\([\s\S]*?;\s*$/,
  "",
);

const values = new Map([
  ["#startAt", "2025-07-01T08:00"],
  ["#workMinutes", "240"],
  ["#driverCount", "2"],
  ["#vehicleCapacity", "8"],
]);
const elements = new Map();
const element = (selector) => {
  if (!elements.has(selector)) {
    elements.set(selector, {
      value: values.get(selector) ?? "",
      checked: selector === "#useTmap" ? false : undefined,
      innerHTML: "",
      textContent: "",
      style: {},
      classList: { add() {}, remove() {}, toggle() {} },
      prepend() {},
    });
  }
  return elements.get(selector);
};
const document = {
  querySelector(selector) {
    return element(selector);
  },
  createElement() { return element(`#created-${elements.size}`); },
  head: { appendChild() {} },
};
const localStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
class FakeLatLng {
  constructor(lat, lng) { this.lat = lat; this.lng = lng; }
}
class FakeBounds { extend() {} }
class FakeMap { fitBounds() {} }
class FakeLayer {
  constructor(options) { this.options = options; this.map = options.map; }
  setMap(map) { this.map = map; }
}
const Tmapv2 = {
  LatLng: FakeLatLng,
  LatLngBounds: FakeBounds,
  Map: FakeMap,
  Polyline: FakeLayer,
  Marker: FakeLayer,
};
const window = { Tmapv2 };
const makeHarness = new Function(
  "document",
  "localStorage",
  "fetch",
  "window",
  "Tmapv2",
  `${testableScript}; return { state, normalizeScenario, buildScenarioRequest, renderPlan, renderTmapPlan };`,
);
const harness = makeHarness(document, localStorage, async () => {
  throw new Error("panel network access is not expected in the parser harness");
}, window, Tmapv2);

const sampleResponse = await fetch(
  "http://127.0.0.1:8765/api/v1/test/core-scenarios/sample",
);
if (!sampleResponse.ok) throw new Error(await sampleResponse.text());
harness.state.scenario = harness.normalizeScenario(await sampleResponse.json());
const request = harness.buildScenarioRequest();
if (request.core.stations.length !== 5) throw new Error("core station count mismatch");
if (request.driver_count !== 2) throw new Error("driver count mismatch");

const response = await fetch(
  "http://127.0.0.1:8765/api/v1/test/core-scenarios/plan",
  {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Test-Role": "admin" },
    body: JSON.stringify(request),
  },
);
if (!response.ok) throw new Error(`core plan API failed: ${await response.text()}`);
const plan = await response.json();
if (!plan.map_data.routes.length) throw new Error("map routes are missing");
if (!plan.published_mission_ids.length) throw new Error("missions were not published");
harness.state.plan = plan;
harness.renderPlan();
await harness.renderTmapPlan();
if (harness.state.routeLayers.size !== plan.map_data.routes.length) {
  throw new Error("TMAP route layers were not rendered");
}
if (!elements.get("#routeLegend").innerHTML.includes("route-card")) {
  throw new Error("driver route legend was not rendered");
}

console.log("panel core JSON, TMAP layers, and route API flow OK");
