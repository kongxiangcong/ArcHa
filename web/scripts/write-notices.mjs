// Preserve installed production dependency licenses alongside bundled assets.
import { readFile, readdir, writeFile } from "node:fs/promises";
const root = new URL("../", import.meta.url);
const lock = JSON.parse(
  await readFile(new URL("package-lock.json", root), "utf8"),
);
const sections = [
  "ArcHa observer frontend — third-party notices\nVersions are locked by web/package-lock.json.\n",
];
for (const [path, entry] of Object.entries(lock.packages)) {
  if (!path || entry.dev) continue;
  const dir = new URL(path + "/", root);
  const files = await readdir(dir).catch(() => []);
  const licenses = files.filter((name) =>
    /^(licen[sc]e|copying|notice)(\.|$)/i.test(name),
  );
  sections.push(
    `\n--- ${path.replace(/^node_modules\//, "")} @ ${entry.version} ---\n`,
  );
  for (const name of licenses) {
    const text = await readFile(new URL(name, dir), "utf8").catch(() => null);
    if (text) sections.push(`${name}\n${text}\n`);
  }
  if (!licenses.length)
    sections.push(
      `License metadata: ${entry.license ?? "see upstream package metadata"}\n`,
    );
}
await writeFile(
  new URL("../opc/observer/static/THIRD_PARTY_NOTICES.txt", root),
  sections.join("\n"),
);
