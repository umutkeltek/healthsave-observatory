#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, rmSync, statSync } from "node:fs";
import path from "node:path";
import process from "node:process";

const VERSION = "0.1.3";
const PRIMARY_COMMAND = "healthsave";
const ALIAS_COMMAND = "healthsave-observatory";
const DEFAULT_REPO =
  process.env.HEALTHSAVE_OBSERVATORY_REPO ||
  "https://github.com/umutkeltek/healthsave-observatory.git";
const DEFAULT_REF = process.env.HEALTHSAVE_OBSERVATORY_REF || "v0.1.3";
const DEFAULT_HOME = process.env.HOME || process.env.USERPROFILE || process.cwd();
const DEFAULT_DIR =
  process.env.HEALTHSAVE_OBSERVATORY_HOME ||
  path.join(DEFAULT_HOME, "healthsave-observatory");
const PLATFORM = process.env.HEALTHSAVE_TEST_PLATFORM || process.platform;
const SETUP_COMMANDS = new Set(["init", "onboard", "setup", "install", ""]);
const DELEGATED_COMMANDS = new Set([
  "doctor",
  "tui",
  "menu",
  "status",
  "layers",
  "logs",
  "up",
  "down",
  "verify",
  "install-cli",
  "uninstall-cli",
]);

function usage() {
  return `HealthSave CLI

Usage:
  ${PRIMARY_COMMAND}
  ${PRIMARY_COMMAND} onboard [dir]
  ${PRIMARY_COMMAND} init [dir]
  ${PRIMARY_COMMAND} setup [basic|advanced] [dir] [flags]
  ${PRIMARY_COMMAND} doctor [dir] [--json]
  ${PRIMARY_COMMAND} status [dir] [--json]
  ${PRIMARY_COMMAND} layers [dir] [--json]
  ${PRIMARY_COMMAND} logs [dir] [layer]
  ${PRIMARY_COMMAND} up [dir] [flags]
  ${PRIMARY_COMMAND} down [dir]
  ${PRIMARY_COMMAND} verify [dir]
  ${PRIMARY_COMMAND} version

Examples:
  npm i -g healthsave
  healthsave onboard
  npx healthsave
  healthsave doctor
  healthsave setup basic --no-input
  npx healthsave init /srv/healthsave-observatory
  npx healthsave doctor --dir /srv/healthsave-observatory --json

Flags:
  --dir DIR             Stack checkout directory. Defaults to ~/healthsave-observatory.
  --repo URL            Git repository for new checkout.
  --ref REF             Git tag, branch, or commit for new checkout. Default: ${DEFAULT_REF}.
  --json                Machine-readable output where supported.
  --dry-run             Show planned bootstrap/setup action.
  --install-cli         Explicitly install a checkout-local wrapper after init/onboard/setup.
  --install-name NAME   Wrapper name when --install-cli is used. Default: healthsave.
  --no-install-cli      Compatibility no-op; package managers own the public command.
  -h, --help            Show this help.
  --version             Print npm bootstrapper version.

Alias:
  ${ALIAS_COMMAND} is installed by the same npm package.

Requirements:
  Node.js >=18 and Git are required for npm/npx checkout bootstrap.
  Docker Compose v2 must be installed and running before stack setup.
  Native Windows uses WSL2 today:
  irm https://raw.githubusercontent.com/umutkeltek/healthsave-observatory/main/install.ps1 | iex
`;
}

function fail(message, code = 1, json = false) {
  if (json) {
    process.stdout.write(`${JSON.stringify({ ok: false, error: message }, null, 2)}\n`);
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

function requireValue(argv, index, flag) {
  if (index >= argv.length || argv[index].startsWith("--")) {
    fail(`${flag} needs a value`, 2);
  }
  return argv[index];
}

function defaultOptions() {
  return {
    dir: "",
    repo: DEFAULT_REPO,
    ref: DEFAULT_REF,
    installName: PRIMARY_COMMAND,
    installCli: false,
    dryRun: false,
    json: false,
    help: false,
    version: false,
  };
}

function consumeGlobalOption(argv, index, options, afterCommand, command, commandArgs) {
  const arg = argv[index];
  const setupCommand = SETUP_COMMANDS.has(command);

  if (arg === "--dir") {
    options.dir = path.resolve(requireValue(argv, index + 1, arg));
    return 2;
  }
  if (arg === "--json") {
    options.json = true;
    return 1;
  }
  if (arg === "--dry-run") {
    options.dryRun = true;
    if (afterCommand) commandArgs.push(arg);
    return 1;
  }
  if (!afterCommand || setupCommand) {
    if (arg === "--repo") {
      options.repo = requireValue(argv, index + 1, arg);
      return 2;
    }
    if (arg === "--ref") {
      options.ref = requireValue(argv, index + 1, arg);
      return 2;
    }
    if (arg === "--install-name") {
      options.installName = requireValue(argv, index + 1, arg);
      return 2;
    }
    if (arg === "--install-cli") {
      options.installCli = true;
      return 1;
    }
    if (arg === "--no-install-cli") {
      options.installCli = false;
      return 1;
    }
  }
  if (!afterCommand && (arg === "-h" || arg === "--help")) {
    options.help = true;
    return 1;
  }
  if (!afterCommand && arg === "--version") {
    options.version = true;
    return 1;
  }

  return 0;
}

function parseArgs(argv) {
  const options = defaultOptions();
  let command = "";
  const commandArgs = [];

  for (let index = 0; index < argv.length; ) {
    const arg = argv[index];

    if (arg === "--") {
      commandArgs.push(...argv.slice(index + 1));
      break;
    }

    if (!command) {
      const consumed = consumeGlobalOption(argv, index, options, false, command, commandArgs);
      if (consumed) {
        index += consumed;
        continue;
      }
      if (arg.startsWith("--")) {
        fail(`Unknown option before command: ${arg}`, 2, options.json);
      }
      command = arg;
      index += 1;
      continue;
    }

    if (arg === "-h" || arg === "--help") {
      commandArgs.push(arg);
      index += 1;
      continue;
    }

    const consumed = consumeGlobalOption(argv, index, options, true, command, commandArgs);
    if (consumed) {
      index += consumed;
      continue;
    }

    commandArgs.push(arg);
    index += 1;
  }

  return { options, command, commandArgs };
}

function assertSupportedPlatform(options) {
  if (PLATFORM !== "win32") return;
  fail(
    "Native Windows is not supported yet. Use PowerShell WSL2 handoff: irm https://raw.githubusercontent.com/umutkeltek/healthsave-observatory/main/install.ps1 | iex",
    1,
    options.json,
  );
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

function capture(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd || process.cwd(),
    stdio: "pipe",
    encoding: "utf8",
  });
  if (result.error || result.status !== 0) return "";
  return (result.stdout || "").trim();
}

function gitAvailable() {
  const result = spawnSync("git", ["--version"], { stdio: "ignore" });
  return !result.error && result.status === 0;
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
    if (isCheckout(current)) return current;
    const parent = path.dirname(current);
    if (parent === current) return "";
    current = parent;
  }
}

function isEmptyDir(dir) {
  return existsSync(dir) && statSync(dir).isDirectory() && readdirSync(dir).length === 0;
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

function expandPath(value) {
  if (value === "~") return DEFAULT_HOME;
  if (value.startsWith("~/")) return path.join(DEFAULT_HOME, value.slice(2));
  return path.resolve(value);
}

function shellQuote(value) {
  if (/^[A-Za-z0-9_./:=@%+-]+$/.test(value)) return value;
  return `'${value.replaceAll("'", "'\\''")}'`;
}

function defaultStackDir() {
  const discovered = findCheckout(process.cwd());
  return discovered || path.resolve(DEFAULT_DIR);
}

function stackDirFromArgs(commandArgs, options, offset = 0, removeFromArgs = false) {
  if (options.dir) {
    return { dir: options.dir, args: [...commandArgs] };
  }

  const maybeDir = commandArgs[offset];
  if (maybeDir && !maybeDir.startsWith("-")) {
    const args = [...commandArgs];
    if (removeFromArgs) args.splice(offset, 1);
    return { dir: expandPath(maybeDir), args };
  }

  return { dir: defaultStackDir(), args: [...commandArgs] };
}

function splitDelegateArgs(command, commandArgs, options) {
  if (options.dir) return { dir: options.dir, args: [...commandArgs] };

  const first = commandArgs[0];
  if (first && !first.startsWith("-") && (looksLikePath(first) || isCheckout(expandPath(first)))) {
    return { dir: expandPath(first), args: commandArgs.slice(1) };
  }

  return { dir: defaultStackDir(), args: [...commandArgs] };
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
    process.stdout.write(`Would checkout ref ${options.ref}\n`);
    if (options.installCli) {
      process.stdout.write(`Would install wrapper command: ${options.installName}\n`);
    }
    return dir;
  }

  if (!gitAvailable()) {
    fail("Git is required for fresh npm/npx checkout bootstrap. Install Git or use an existing checkout with --dir.", 1, options.json);
  }

  mkdirSync(path.dirname(dir), { recursive: true });
  info(`Cloning ${options.repo} into ${dir}`);
  let result = run("git", ["clone", options.repo, dir], { json: options.json });
  if (result.status !== 0) process.exit(result.status || 1);

  info(`Checking out ${options.ref}`);
  result = run("git", ["-C", dir, "checkout", options.ref], { json: options.json });
  if (result.status !== 0) {
    rmSync(dir, { recursive: true, force: true });
    process.exit(result.status || 1);
  }

  if (!isCheckout(dir)) {
    fail(`${dir} cloned, but does not contain HealthSave Observatory stack files.`, 1, options.json);
  }

  return dir;
}

function installWrapper(dir, options) {
  if (!options.installCli || options.dryRun) return;
  const result = run(path.join(dir, "healthsave"), ["install-cli", "--name", options.installName], {
    cwd: dir,
    stdio: "inherit",
  });
  if (result.status !== 0) {
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

function commandInit(commandArgs, options) {
  const { dir } = stackDirFromArgs(commandArgs, options, 0, false);
  ensureCheckout(dir, options);
  installWrapper(dir, options);
  if (!options.dryRun) {
    ok(`HealthSave Observatory stack ready at ${dir}`);
    process.stdout.write(`Next:\n  cd ${shellQuote(dir)}\n  ./healthsave onboard\n`);
  }
}

function commandOnboard(commandArgs, options) {
  const { dir } = stackDirFromArgs(commandArgs, options, 0, true);
  ensureCheckout(dir, options);
  installWrapper(dir, options);
  if (options.dryRun) {
    process.stdout.write(`Would open interactive control center: healthsave onboard --dir ${dir}\n`);
    return;
  }
  delegate(dir, ["onboard"], options);
}

function commandSetup(commandArgs, options) {
  let mode = "";
  let dirOffset = 0;
  if (["basic", "advanced"].includes(commandArgs[0])) {
    mode = commandArgs[0];
    dirOffset = 1;
  }

  const { dir, args } = stackDirFromArgs(commandArgs, options, dirOffset, true);
  const delegatedArgs = mode ? args : args;
  ensureCheckout(dir, options);
  installWrapper(dir, options);
  if (options.dryRun && !isCheckout(dir)) return;
  delegate(dir, ["setup", ...delegatedArgs], options);
}

function commandDelegate(command, commandArgs, options) {
  const { dir, args } = splitDelegateArgs(command, commandArgs, options);
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

  let delegatedArgs = [...args];
  if (
    ["install-cli", "uninstall-cli"].includes(command) &&
    options.installName !== PRIMARY_COMMAND &&
    !delegatedArgs.includes("--name")
  ) {
    delegatedArgs = ["--name", options.installName, ...delegatedArgs];
  }
  const finalArgs = options.json ? ["--json", command, ...delegatedArgs] : [command, ...delegatedArgs];
  delegate(dir, finalArgs, options);
}

function checkoutIdentity(dir) {
  if (!dir || !isCheckout(dir)) return null;
  const coreVersion = capture(path.join(dir, "healthsave"), ["version"], { cwd: dir });
  const commit = capture("git", ["-C", dir, "rev-parse", "--short", "HEAD"]);
  const dirty = capture("git", ["-C", dir, "status", "--porcelain"]) ? "dirty" : "clean";
  return {
    dir,
    core_version: coreVersion || null,
    git_commit: commit || null,
    git_state: commit ? dirty : "unknown",
  };
}

function commandVersion(options) {
  const discovered = findCheckout(process.cwd());
  const homeCheckout = isCheckout(path.resolve(DEFAULT_DIR)) ? path.resolve(DEFAULT_DIR) : "";
  const checkout = checkoutIdentity(options.dir || discovered || homeCheckout);

  if (options.json) {
    process.stdout.write(
      `${JSON.stringify(
        {
          ok: true,
          bootstrapper: { name: PRIMARY_COMMAND, version: VERSION, default_ref: options.ref },
          checkout,
        },
        null,
        2,
      )}\n`,
    );
    return;
  }

  process.stdout.write(`${PRIMARY_COMMAND} npm ${VERSION}\n`);
  process.stdout.write(`default checkout ref ${options.ref}\n`);
  if (checkout) {
    process.stdout.write(`checkout ${checkout.dir}\n`);
    if (checkout.core_version) process.stdout.write(`core ${checkout.core_version}\n`);
    if (checkout.git_commit) process.stdout.write(`git ${checkout.git_commit} ${checkout.git_state}\n`);
  } else {
    process.stdout.write("checkout not found\n");
  }
}

function main() {
  const { options, command, commandArgs } = parseArgs(process.argv.slice(2));

  if (options.version) {
    process.stdout.write(`${PRIMARY_COMMAND} ${VERSION}\n`);
    return;
  }
  if (options.help || command === "help") {
    process.stdout.write(usage());
    return;
  }

  assertSupportedPlatform(options);

  if (!command || looksLikePath(command)) {
    commandOnboard(command ? [command, ...commandArgs] : commandArgs, options);
    return;
  }

  switch (command) {
    case "version":
      commandVersion(options);
      return;
    case "init":
      commandInit(commandArgs, options);
      return;
    case "setup":
    case "install":
      commandSetup(commandArgs, options);
      return;
    case "onboard":
      commandOnboard(commandArgs, options);
      return;
    default:
      if (DELEGATED_COMMANDS.has(command)) {
        commandDelegate(command, commandArgs, options);
        return;
      }
      fail(`Unknown command: ${command}`, 2, options.json);
  }
}

main();
