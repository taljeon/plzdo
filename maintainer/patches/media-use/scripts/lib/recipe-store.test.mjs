import assert from "node:assert/strict";
import {
  existsSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  readlinkSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { readManifest } from "./manifest.mjs";
import { freezeRecipe, listRecipes, useRecipe } from "./recipe-store.mjs";

const SLUG = "demo";
const ENV_KEYS = ["HYPERFRAMES_MEDIA_HOME", "HYPERFRAMES_MEDIA_HOME_REQUIRED"];

function fixture(t) {
  const root = mkdtempSync(join(tmpdir(), "mu-recipe-"));
  const savedEnv = Object.fromEntries(ENV_KEYS.map((key) => [key, process.env[key]]));
  t.after(() => {
    for (const key of ENV_KEYS) {
      if (savedEnv[key] === undefined) delete process.env[key];
      else process.env[key] = savedEnv[key];
    }
    rmSync(root, { recursive: true, force: true });
  });
  const project = join(root, "project");
  const outside = join(root, "outside");
  const home = join(root, "home");
  for (const dir of [project, outside, home]) mkdirSync(dir);
  writeFileSync(join(project, "frame.md"), "# Design\nBlue background.\n");
  writeFileSync(join(project, "STORYBOARD.md"), "## Frame 1 — Intro\n- status: approved\nHello.\n");
  writeFileSync(join(project, "BRIEF.md"), "---\nworkflow: demo\n---\n## Message\nHello.\n");
  writeFileSync(join(outside, "sentinel.txt"), "keep outside intact\n");
  process.env.HYPERFRAMES_MEDIA_HOME = home;
  process.env.HYPERFRAMES_MEDIA_HOME_REQUIRED = "1";
  const recipes = join(project, ".media", "recipes");
  return {
    root,
    project,
    outside,
    home,
    recipes,
    dir: join(recipes, SLUG),
    freeze: () => freezeRecipe({ projectDir: project, name: SLUG }),
  };
}

function snapshot(root) {
  const entries = [];
  function visit(relative) {
    const path = join(root, relative);
    const stat = lstatSync(path);
    if (stat.isSymbolicLink()) {
      entries.push([relative, "symlink", readlinkSync(path)]);
    } else if (stat.isDirectory()) {
      entries.push([relative, "directory"]);
      for (const name of readdirSync(path).sort()) visit(join(relative, name));
    } else {
      entries.push([relative, "file", readFileSync(path).toString("base64")]);
    }
  }
  visit(".");
  return entries;
}

function writeStored(f, source) {
  mkdirSync(f.dir, { recursive: true });
  writeFileSync(join(f.dir, "recipe.json"), source);
  writeFileSync(join(f.dir, "sentinel.txt"), "keep current recipe intact\n");
}

function assertRejectedUnchanged(f, message) {
  const before = snapshot(f.root);
  try {
    assert.throws(f.freeze, { name: "Error", message });
  } finally {
    assert.deepEqual(snapshot(f.root), before);
  }
}

const invalidVersions = [
  ["traversal 1/../../../outside", '"1/../../../outside"'],
  ["traversal ../../outside", '"../../outside"'],
  // Four parent segments reach the sibling outside/ from the archive prefix.
  ["traversal to sibling outside", '"1/../../../../outside"'],
  ["numeric string", '"2"'],
  ["object", "{}"],
  ["array", "[]"],
  ["null", "null"],
  ["true", "true"],
  ["false", "false"],
  ["zero", "0"],
  ["negative", "-1"],
  ["fraction", "1.5"],
  ["next version overflow", String(Number.MAX_SAFE_INTEGER)],
  ["above MAX_SAFE_INTEGER literal", "9007199254740992"],
  ["Infinity from JSON exponent", "1e400"],
];

for (const [label, literal] of invalidVersions) {
  test(`freeze rejects stored version: ${label} without changes`, (t) => {
    const f = fixture(t);
    writeStored(f, `{"name":"${SLUG}","version":${literal}}\n`);
    if (label.startsWith("traversal")) {
      mkdirSync(join(f.recipes, `${SLUG}@v1`));
      mkdirSync(join(f.recipes, `${SLUG}@v..`));
    }
    assertRejectedUnchanged(f, /invalid stored version.*fix or remove \.media\/recipes\/demo\/recipe\.json/);
  });
}

test("freeze versions 1, 2 and 3 preserves archives, promotion, manifest, list and use", (t) => {
  const f = fixture(t);
  const first = f.freeze();
  assert.equal(first.version, 1);
  assert.equal(first.workflow, "demo");
  const firstJson = readFileSync(join(f.dir, "recipe.json"), "utf8");
  assert.equal(JSON.parse(firstJson).version, 1);
  const firstSnapshot = snapshot(f.dir);

  assert.equal(f.freeze().version, 2);
  const archive1 = join(f.recipes, `${SLUG}@v1`);
  assert.equal(readFileSync(join(archive1, "recipe.json"), "utf8"), firstJson);
  assert.deepEqual(snapshot(archive1), firstSnapshot);
  assert.equal(JSON.parse(readFileSync(join(f.dir, "recipe.json"), "utf8")).version, 2);
  const secondSnapshot = snapshot(f.dir);

  assert.equal(f.freeze().version, 3);
  assert.deepEqual(snapshot(join(f.recipes, `${SLUG}@v2`)), secondSnapshot);
  assert.deepEqual(snapshot(archive1), firstSnapshot);
  assert.equal(JSON.parse(readFileSync(join(f.dir, "recipe.json"), "utf8")).version, 3);
  assert.deepEqual(snapshot(join(f.home, ".media", "recipes", SLUG)), snapshot(f.dir));
  assert.deepEqual(readManifest(f.project).map((record) => record.provenance.version), [1, 2, 3]);
  const listed = listRecipes({ projectDir: f.project });
  assert.equal(listed.length, 1);
  assert.equal(listed[0].version, 3);
  assert.equal(listed[0].source, "project");
  writeFileSync(join(f.project, "frame.md"), "replacement\n");
  assert.equal(useRecipe({ projectDir: f.project, name: SLUG }).recipe.version, 3);
  assert.equal(readFileSync(join(f.project, "frame.md"), "utf8"), readFileSync(join(f.dir, "frame.md"), "utf8"));
  assert.equal(readFileSync(join(f.outside, "sentinel.txt"), "utf8"), "keep outside intact\n");
});

test("freeze treats only a missing version key as legacy v1", (t) => {
  const f = fixture(t);
  writeStored(f, `{"name":"${SLUG}"}\n`);
  const before = snapshot(f.dir);
  assert.equal(f.freeze().version, 2);
  assert.deepEqual(snapshot(join(f.recipes, `${SLUG}@v1`)), before);
  assert.equal(JSON.parse(readFileSync(join(f.dir, "recipe.json"), "utf8")).version, 2);
});

test("freeze rejects an existing archive folder without changes", (t) => {
  const f = fixture(t);
  writeStored(f, `{"name":"${SLUG}","version":1}\n`);
  const archive = join(f.recipes, `${SLUG}@v1`);
  mkdirSync(archive);
  writeFileSync(join(archive, "sentinel.txt"), "keep archive intact\n");
  assertRejectedUnchanged(f, /archive.*already exists; nothing was changed/);
});

test("freeze rejects a dangling archive symlink without changes", (t) => {
  const f = fixture(t);
  writeStored(f, `{"name":"${SLUG}","version":1}\n`);
  symlinkSync(join(f.root, "missing"), join(f.recipes, `${SLUG}@v1`), "dir");
  assertRejectedUnchanged(f, /archive.*already exists; nothing was changed/);
});

test("freeze rejects a recipe folder symlink to outside without changes", (t) => {
  const f = fixture(t);
  mkdirSync(f.recipes, { recursive: true });
  writeFileSync(join(f.outside, "recipe.json"), `{"name":"${SLUG}","version":1}\n`);
  symlinkSync(f.outside, f.dir, "dir");
  assertRejectedUnchanged(f, /folder is a symbolic link; nothing was changed/);
});

// A planted file link inside the recipe folder would otherwise be written through on the fresh-v1 path.
for (const file of ["recipe.json", "frame.md", "storyboard-skeleton.md", "brief-skeleton.md"]) {
  test(`freeze rejects a planted ${file} link to outside without changes`, (t) => {
    const f = fixture(t);
    mkdirSync(f.dir, { recursive: true });
    symlinkSync(join(f.outside, "sentinel.txt"), join(f.dir, file));
    assertRejectedUnchanged(f, new RegExp(`${file.replace(".", "\\.")} is not a regular file; nothing was changed`));
  });
}

for (const folder of [".media", ".media/recipes"]) {
  test(`freeze rejects ${folder} as a link to outside without changes`, (t) => {
    const f = fixture(t);
    if (folder === ".media/recipes") mkdirSync(join(f.project, ".media"));
    symlinkSync(f.outside, join(f.project, folder), "dir");
    assertRejectedUnchanged(f, /is a symbolic link; nothing was changed/);
  });
}

for (const [label, source] of [
  ["no name, traversal version", '{"version":"../../outside"}'],
  ["non-string name, string version", '{"name":42,"version":"2"}'],
]) {
  test(`freeze rejects a bad stored version even without a usable name: ${label}`, (t) => {
    const f = fixture(t);
    writeStored(f, source);
    assertRejectedUnchanged(f, /invalid stored version; fix or remove \.media\/recipes\/demo\/recipe\.json/);
  });
}

for (const [label, source] of [
  ["invalid JSON", "{invalid"],
  ["NaN is invalid JSON", '{"name":"demo","version":NaN}'],
  ["missing string name, valid version", '{"name":42,"version":2}'],
]) {
  test(`freeze preserves fresh-v1 fallback for ${label}`, (t) => {
    const f = fixture(t);
    writeStored(f, source);
    assert.equal(f.freeze().version, 1);
    assert.equal(existsSync(join(f.recipes, `${SLUG}@v1`)), false);
    assert.equal(readFileSync(join(f.dir, "sentinel.txt"), "utf8"), "keep current recipe intact\n");
    assert.equal(readFileSync(join(f.outside, "sentinel.txt"), "utf8"), "keep outside intact\n");
  });
}
