#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import process from "node:process";

const VERSION = "0.1.1";
const PRIMARY_COMMAND = "healthsave";
const ALIAS_COMMAND = "healthsave-observatory";
const DEFAULT_REPO =
  process.env.HEALTHSAVE_OBSERVATORY_REPO ||
  "https://github.com/umutkeltek/healthsave-observatory.git";
const DEFAULT_HOME = process.env.HOME || process.env.USERPROFILE || process.cwd();
const DEFAULT_DIR =
  process.env.HEALTHSAVE_OBSERVATORY_HOME ||
  path.join(DEFAULT_HOME, "healthsave-observatory");

function usage() {
  return `HealthSave CLI

Usage:
  ${PRIMARY_COMMAND} [dir]
  ${PRIMARY_COMMAND} onboard [dir]
  ${PRIMARY_COMMAND} tui [dir]
  ${PRIMARY_COMMAND} init [dir] [flags]
  ${PRIMARY_COMMAND} setup [basic|advanced] [dir] [flags]
  ${PRIMARY_COMMAND} doctor [dir] [--json]
  ${PRIMARY_COMMAND} status [dir] [--json]
  ${PRIMARY_COMMAND} layers [dir] [--json]
  ${PRIMARY_COMMAND} logs [dir] [layer]
  ${PRIMARY_COMMAND} up [dir] [flags]
  ${PRIMARY_COMMAND} down [dir]
  ${PRIMARY_COMMAND} verify [dir]

Examples:
  npm i -g healthsave
  healthsave onboard
  npx healthsave
  healthsave doctor
  healthsave setup basic --no-input
  npx healthsave init /srv/healthsave-observatory
  npx healthsave doctor --dir /srv/healthsave-observatory --json

Alias:
  ${ALIAS_COMMAND} is installed by the same npm package for users who prefer the longer name.

Flags:
  --dir DIR             Stack directory (alternative positional dir)
  --repo URL            Git repo clone source (default: ${DEFAULT_REPO})
  --ref REF             Git ref checkout after clone
  --install-name NAME   Wrapper command name installed by stack (default: healthsave)
  --no-install-cli      Do not install local wrapper after init/setup
  --dry-run             Print what would happen
  --json                Machine-readable output for supported delegated commands
  -h, --help            Show help
  --version             Show version
`;
}

function parseArgs(argv) {
  const options = {
    dir: "",
    repo: DEFAULT_REPO,
    ref: "",
    installName: "healthsave",
    noInstallCli: false,
    dryRun: false,
    json: false,
    help: false,
    version: false,
  };
  const positionals = [];
  const passthrough = [];

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];

    switch (arg) {
      case "--dir":
        options.dir = requireValue(argv, (index += 1), arg);
        break;
      case "--repo":
        options.repo = requireValue(argv, (index += 1), arg);
        break;
      case "--ref":
        options.ref = requireValue(argv, (index += 1), arg);
        break;
      case "--install-name":
        options.installName = requireValue(argv, (index += 1), arg);
        break;
      case "--no-install-cli":
        options.noInstallCli = true;
        break;
      case "--dry-run":
        options.dryRun = true;
        passthrough.push(arg);
        break;
      case "--json":
        options.json = true;
        break;
      case "-h":
      case "--help":
        options.help = true;
        break;
      case "--version":
        options.version = true;
        break;
      default:
        if (arg.startsWith("--")) {
          passthrough.push(arg);
        } else {
          positionals.push(arg);
        }
    }
  }

  return { options, positionals, passthrough };
}

function requireValue(argv, index, flag) {
  if (index >= argv.length || argv[index].startsWith("--")) {
    fail(`${flag} needs a value`, 2);
  }
  return argv[index];
}

function fail(message, code = 1, json = false) {
  if (json) {
    process.stdout.write(
      `${JSON.stringify({ ok: false, error: message }, null, 2)}\n`,
    );
  } else {
    process.stderr.write(`[ERR] ${message}\n`);
  }
  process.exit(code);
}

function info(message) {
  process.stderr.write(`[INFO] ${message}\n`);
}

function ok(message) {
  process.stderr.write(`[OK] ${message}\n`);
}

function isCheckout(dir) {
  return (
    existsSync(path.join(dir, "healthsave")) &&
    existsSync(path.join(dir, "setup.sh")) &&
    existsSync(path.join(dir, "docker-compose.yml"))
  );
}

function findCheckout(startDir) {
  let current = path.resolve(startDir);
  while (true) {
    if (isCheckout(current)) {
      return current;
    }
    const parent = path.dirname(current);
    if (parent === current) {
      return "";
    }
    current = parent;
  }
}

function isEmptyDir(dir) {
  return existsSync(dir) && statSync(dir).isDirectory() && readdirSync(dir).length === 0;
}

function stackDirFromArgs(positionals, options, offset = 1) {
  if (options.dir) {
    return path.resolve(options.dir);
  }

  const maybeDir = positionals[offset];
  if (maybeDir && !maybeDir.startsWith("-")) {
    return path.resolve(maybeDir);
  }

  const discovered = findCheckout(process.cwd());
  return discovered || path.resolve(DEFAULT_DIR);
}

function looksLikePath(value) {
  return (
    value.startsWith("/") ||
    value.startsWith(".") ||
    value.startsWith("~") ||
    value.includes("/") ||
    value.includes("\\")
  );
}

function splitDelegateArgs(command, positionals, options) {
  const rest = positionals.slice(1);
  if (options.dir) {
    return { dir: path.resolve(options.dir), args: rest };
  }

  const first = rest[0];
  if (first && (looksLikePath(first) || isCheckout(path.resolve(first)) || command !== "logs")) {
    return { dir: path.resolve(first), args: rest.slice(1) };
  }

  const discovered = findCheckout(process.cwd());
  return { dir: discovered || path.resolve(DEFAULT_DIR), args: rest };
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd || process.cwd(),
    stdio: options.stdio || "inherit",
    encoding: "utf8",
  });

  if (result.error) {
    fail(`${command} failed: ${result.error.message}`, 1, options.json);
  }

  return result;
}

function ensureCheckout(dir, options) {
  if (isCheckout(dir)) {
    return dir;
  }

  if (existsSync(dir) && !isEmptyDir(dir)) {
    fail(
      `${dir} exists but is not a HealthSave Observatory checkout. Pick an empty directory or pass --dir for an existing checkout.`,
      1,
      options.json,
    );
  }

  if (options.dryRun) {
    process.stdout.write(`Would clone ${options.repo} into ${dir}\n`);
    if (options.ref) {
      process.stdout.write(`Would checkout ref ${options.ref}\n`);
    }
    if (!options.noInstallCli) {
      process.stdout.write(`Would install wrapper command: ${options.installName}\n`);
    }
    return dir;
  }

  mkdirSync(path.dirname(dir), { recursive: true });
  info(`Cloning ${options.repo} into ${dir}`);
  let result = run("git", ["clone", options.repo, dir], { json: options.json });
  if (result.status !== 0) {
    process.exit(result.status || 1);
  }

  if (options.ref) {
    info(`Checking out ${options.ref}`);
    result = run("git", ["-C", dir, "checkout", options.ref], { json: options.json });
    if (result.status !== 0) {
      process.exit(result.status || 1);
    }
  }

  if (!isCheckout(dir)) {
    fail(`${dir} cloned, but does not contain HealthSave Observatory stack files.`, 1, options.json);
  }

  return dir;
}

function installWrapper(dir, options, allowFailure = false) {
  if (options.noInstallCli || options.dryRun) {
    return;
  }

  const result = run(path.join(dir, "healthsave"), ["install-cli", "--name", options.installName], {
    cwd: dir,
    stdio: "inherit",
  });
  if (result.status !== 0) {
    if (allowFailure) {
      process.stderr.write(
        `[WARN] Could not install ${options.installName}; setup can still continue inside ${dir}.\n`,
      );
      return;
    }
    process.exit(result.status || 1);
  }
}

function delegate(dir, healthsaveArgs, options) {
  const bin = path.join(dir, "healthsave");
  if (!existsSync(bin)) {
    fail(`${dir} does not contain ./healthsave. Run ${PRIMARY_COMMAND} init ${dir}`, 1, options.json);
  }

  const result = run(bin, healthsaveArgs, {
    cwd: dir,
    stdio: "inherit",
    json: options.json,
  });
  process.exit(result.status || 0);
}

function commandInit(positionals, options) {
  const dir = stackDirFromArgs(positionals, options, 1);
  ensureCheckout(dir, options);
  installWrapper(dir, options);
  if (!options.dryRun) {
    ok(`HealthSave Observatory stack ready at ${dir}`);
    process.stdout.write(`Next:\n  cd ${dir}\n  ${options.installName} onboard\n`);
  }
}

function commandOnboard(positionals, options) {
  const dir = stackDirFromArgs(["onboard", ...positionals], options, 1);
  ensureCheckout(dir, options);
  installWrapper(dir, options, true);
  if (options.dryRun) {
    process.stdout.write(`Would open interactive control center: ${options.installName} onboard\n`);
    return;
  }
  delegate(dir, ["onboard"], options);
}

function commandSetup(positionals, options, passthrough) {
  let mode = "basic";
  let dirOffset = 1;

  if (positionals[1] && ["basic", "advanced"].includes(positionals[1])) {
    mode = positionals[1];
    dirOffset = 2;
  } else if (positionals[1] && positionals[1].startsWith("-")) {
    fail("setup mode must be basic or advanced", 2, options.json);
  }

  const dir = stackDirFromArgs(positionals, options, dirOffset);
  ensureCheckout(dir, options);
  installWrapper(dir, options, true);
  if (options.dryRun && !isCheckout(dir)) {
    return;
  }
  delegate(dir, ["setup", mode, ...passthrough], options);
}

function commandDelegate(command, positionals, options, passthrough) {
  const { dir, args: delegatedPositionals } = splitDelegateArgs(command, positionals, options);
  if (!isCheckout(dir)) {
    if (options.json) {
      process.stdout.write(
        `${JSON.stringify(
          {
            ok: false,
            stack_dir: null,
            error: `No HealthSave Observatory checkout found at ${dir}`,
            next: `${PRIMARY_COMMAND} init ${dir}`,
          },
          null,
          2,
        )}\n`,
      );
      process.exit(1);
    }
    fail(`No HealthSave Observatory checkout found at ${dir}. Run: ${PRIMARY_COMMAND} init ${dir}`);
  }

  const args = options.json
    ? ["--json", command, ...delegatedPositionals, ...passthrough]
    : [command, ...delegatedPositionals, ...passthrough];
  delegate(dir, args, options);
}

function main() {
  const { options, positionals, passthrough } = parseArgs(process.argv.slice(2));
  const command = positionals[0] || "";

  if (options.version) {
    process.stdout.write(`${PRIMARY_COMMAND} ${VERSION}\n`);
    return;
  }

  if (options.help || command === "help") {
    process.stdout.write(usage());
    return;
  }

  if (!command || looksLikePath(command)) {
    commandOnboard(positionals, options);
    return;
  }

  switch (command) {
    case "init":
      commandInit(positionals, options);
      return;
    case "setup":
    case "install":
      commandSetup(positionals, options, passthrough);
      return;
    case "onboard":
      commandOnboard(positionals.slice(1), options);
      return;
    case "doctor":
    case "tui":
    case "menu":
    case "status":
    case "layers":
    case "logs":
    case "up":
    case "down":
    case "verify":
    case "install-cli":
      commandDelegate(command, positionals, options, passthrough);
      return;
    default:
      fail(`Unknown command: ${command}`, 2, options.json);
  }
}

main();
