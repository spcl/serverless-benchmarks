// Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
//
// Passive, best-effort introspection of the function's execution environment.
//
// The static record (runtime, OS, CPU, limits, virtualization hints)
// is collected on the first invocation in a process. Later invocations
// return only the kernel boot id.
//
// Only reads local files and process state. A failing probe in the static record
// leaves its value as null and records the reason in the record's `unavailable`
// map. An unreadable boot id is null.

const fs = require('fs'), os = require('os'), path = require('path');

// Lambda runtime identifier, and how the sandbox was started (on-demand,
// provisioned-concurrency, or snap-start).
const ENV_ALLOWLIST = [
  'AWS_EXECUTION_ENV',
  'AWS_LAMBDA_INITIALIZATION_TYPE',
];

let collected = false;

function read(file) {
  return fs.readFileSync(file, 'utf8').trim();
}

function firstExisting(...files) {
  const file = files.find((f) => fs.existsSync(f));
  if (file === undefined)
    throw new Error(`${files[0]} does not exist`);
  return read(file);
}

// cgroup v2 limits live in the process's own cgroup, given as "0::<path>".
function cgroupLimit(name, v1Path) {
  const own = read('/proc/self/cgroup').split('\n')
    .filter((line) => line.startsWith('0::'))
    .map((line) => line.slice(3))[0] || '';
  return firstExisting(
    path.join('/sys/fs/cgroup', own, name), path.join('/sys/fs/cgroup', name), v1Path);
}

function cpuinfo() {
  const fields = {};
  for (const line of read('/proc/cpuinfo').split('\n')) {
    const idx = line.indexOf(':');
    const key = line.slice(0, idx).trim();
    if (idx >= 0 && !(key in fields))
      fields[key] = line.slice(idx + 1).trim();
  }
  const flags = fields['flags'] || fields['Features'] || '';
  return {
    model: fields['model name'] || fields['CPU part'] || null,
    count: os.cpus().length,
    flags: flags.split(/\s+/).filter((flag) => flag !== ''),
  };
}

function osRelease() {
  const fields = {};
  for (const line of read('/etc/os-release').split('\n')) {
    const idx = line.indexOf('=');
    if (idx >= 0)
      fields[line.slice(0, idx)] = line.slice(idx + 1).replace(/^"|"$/g, '');
  }
  const ret = {};
  for (const key of ['ID', 'VERSION_ID', 'PRETTY_NAME'])
    if (key in fields)
      ret[key] = fields[key];
  return ret;
}

function collectStatic() {
  const unavailable = {};
  const probe = (key, fn) => {
    try {
      return fn();
    } catch (e) {
      unavailable[key] = `${e.name}: ${e.message}`;
      return null;
    }
  };
  const env = {};
  for (const key of ENV_ALLOWLIST)
    if (key in process.env)
      env[key] = process.env[key];
  return {
    runtime: {
      name: 'node',
      version: process.version,
      executable: process.execPath,
      versions: process.versions,
    },
    os: {
      system: os.type(),
      release: os.release(),
      version: os.version ? os.version() : null,
      machine: os.machine ? os.machine() : process.arch,
      release_info: probe('os.release_info', osRelease),
    },
    cpu: probe('cpu', cpuinfo),
    memory_total_kb: Math.floor(os.totalmem() / 1024),
    cgroup: {
      cpu_max: probe('cgroup.cpu_max', () => cgroupLimit(
        'cpu.max', '/sys/fs/cgroup/cpu/cpu.cfs_quota_us')),
      memory_max: probe('cgroup.memory_max', () => cgroupLimit(
        'memory.max', '/sys/fs/cgroup/memory/memory.limit_in_bytes')),
    },
    virtualization: {
      dmi_sys_vendor: probe('virtualization.dmi_sys_vendor',
        () => read('/sys/class/dmi/id/sys_vendor')),
      dmi_product_name: probe('virtualization.dmi_product_name',
        () => read('/sys/class/dmi/id/product_name')),
      proc_version: probe('virtualization.proc_version', () => read('/proc/version')),
      kernel_cmdline: probe('virtualization.kernel_cmdline', () => read('/proc/cmdline')),
    },
    env: env,
    unavailable: unavailable,
  };
}

// Environment record for the invocation response.
// Returns the full static record on the first call in this process, otherwise
// only the boot id. Call it once the benchmark timing has stopped.
exports.collect = function() {
  let bootId = null;
  try {
    bootId = read('/proc/sys/kernel/random/boot_id');
  } catch (e) {}

  if (collected)
    return { boot_id: bootId };

  const begin = process.hrtime.bigint();
  const record = collectStatic();
  collected = true;
  return {
    boot_id: bootId,
    probe_us: Number((process.hrtime.bigint() - begin) / 1000n),
    static: record,
  };
};
