#!/usr/bin/env bun
/**
 * Regenerate src/v1.ts and src/v2.ts.
 *
 * - v1.ts: openapi-typescript on contracts/openapi/v1.locked.json (the
 *   v1 wire contract — what HealthSave iOS calls).
 * - v2.ts: json-schema-to-typescript on contracts/json-schema/_bundle.json
 *   (the v2 canonical Pydantic types, bundled into one JSON Schema).
 *
 * --check exits non-zero if regeneration produces a diff against the
 *   committed files. CI uses this. Same drift-check shape as the
 *   v1 lock and v2 schema export.
 */

import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { compile } from "json-schema-to-typescript";
import openapiTS, { astToString } from "openapi-typescript";

const HERE = dirname(fileURLToPath(import.meta.url));
const PKG_ROOT = resolve(HERE, "..");
const REPO_ROOT = resolve(PKG_ROOT, "..", "..", "..");

const V1_OPENAPI = join(REPO_ROOT, "contracts", "openapi", "v1.locked.json");
const V2_BUNDLE = join(REPO_ROOT, "contracts", "json-schema", "_bundle.json");
const V1_OUT = join(PKG_ROOT, "src", "v1.ts");
const V2_OUT = join(PKG_ROOT, "src", "v2.ts");

function header(sourceLabel: string): string {
  return [
    "/**",
    " * AUTO-GENERATED — do not edit.",
    " *",
    " * Regenerate via:",
    " *   make regen-ts-client",
    " *",
    " * Source of truth:",
    ` *   ${sourceLabel}`,
    " */",
    "",
  ].join("\n");
}

async function generateV1(): Promise<string> {
  const ast = await openapiTS(new URL(`file://${V1_OPENAPI}`));
  const body = astToString(ast);
  return header("contracts/openapi/v1.locked.json") + body;
}

/**
 * Pydantic emits `$defs` / `#/$defs/X`; json-schema-to-typescript v15
 * resolves only `definitions` / `#/definitions/X`. Rewrite the bundle
 * to the legacy keyword in-memory before passing it to compile.
 */
function rewriteDefsToDefinitions(node: unknown): unknown {
  if (Array.isArray(node)) {
    return node.map(rewriteDefsToDefinitions);
  }
  if (node && typeof node === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(node)) {
      if (k === "$defs") {
        out.definitions = rewriteDefsToDefinitions(v);
      } else if (k === "$ref" && typeof v === "string") {
        out[k] = v.replace(/^#\/\$defs\//, "#/definitions/");
      } else {
        out[k] = rewriteDefsToDefinitions(v);
      }
    }
    return out;
  }
  return node;
}

async function generateV2(): Promise<string> {
  // The bundle is `{ "$defs": { TypeA: ..., TypeB: ... } }`. We
  // synthesize a Catalog wrapper whose properties $ref each definition,
  // so json-schema-to-typescript walks every type. The Catalog interface
  // itself is a generation artifact and is stripped from the output.
  const bundle = JSON.parse(readFileSync(V2_BUNDLE, "utf-8")) as {
    $defs: Record<string, unknown>;
  };
  const rewritten = rewriteDefsToDefinitions(bundle) as {
    definitions: Record<string, unknown>;
  };
  const defs = rewritten.definitions;
  const names = Object.keys(defs).sort();

  const catalog = {
    title: "_HdhV2Catalog",
    type: "object" as const,
    additionalProperties: false,
    properties: Object.fromEntries(names.map((n) => [n, { $ref: `#/definitions/${n}` }])),
    required: names,
    definitions: defs,
  };

  const raw = await compile(catalog as never, "_HdhV2Catalog", {
    bannerComment: "",
    additionalProperties: false,
    style: { singleQuote: false, semi: true },
  });

  // Strip the synthetic Catalog interface — match its declaration
  // and the trailing blank line. The remaining content is the per-type
  // interfaces we actually want to expose.
  const stripped = raw.replace(
    /export interface _HdhV2Catalog \{[\s\S]*?^\}\s*$/m,
    "",
  );

  return header("contracts/json-schema/_bundle.json") + stripped.trimStart();
}

async function main(): Promise<number> {
  const check = process.argv.includes("--check");

  const v1 = await generateV1();
  const v2 = await generateV2();

  if (check) {
    const drifted: string[] = [];

    if (!existsSync(V1_OUT)) {
      drifted.push(`missing: ${V1_OUT}`);
    } else if (readFileSync(V1_OUT, "utf-8") !== v1) {
      drifted.push(`diff: ${V1_OUT}`);
    }

    if (!existsSync(V2_OUT)) {
      drifted.push(`missing: ${V2_OUT}`);
    } else if (readFileSync(V2_OUT, "utf-8") !== v2) {
      drifted.push(`diff: ${V2_OUT}`);
    }

    if (drifted.length > 0) {
      console.error("ts-client drift detected:");
      for (const d of drifted) console.error(`  ${d}`);
      console.error("If intentional, run `make regen-ts-client` and commit the diff.");
      return 1;
    }

    console.log("ts-client generated files match committed.");
    return 0;
  }

  writeFileSync(V1_OUT, v1);
  writeFileSync(V2_OUT, v2);
  console.log(`wrote ${V1_OUT}`);
  console.log(`wrote ${V2_OUT}`);
  return 0;
}

const code = await main();
process.exit(code);
