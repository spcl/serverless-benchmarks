/**
 * Post-processing step: replace esbuild's dynamic __require("node:…") helper
 * calls in the bundled dist/ output with static ESM imports.
 *
 * esbuild bundles dependencies that themselves call require() at runtime,
 * turning them into __require("node:fs") style calls. Cloudflare Workers
 * run in an ESM-only environment, so these must be hoisted to top-level
 * import statements that wrangler / the runtime can resolve.
 *
 * Only the top-level requires in *source* files can be handled by esbuild's
 * own external/format options, which is why this step is needed separately.
 *
 * Usage: node postprocess.js   (run from the worker package directory)
 */

'use strict';

const fs = require('fs');
const { join, relative } = require('path');

function getAllJsFiles(dir, fileList = []) {
  if (!fs.existsSync(dir)) return fileList;
  const files = fs.readdirSync(dir, { withFileTypes: true });
  for (const file of files) {
    const filePath = join(dir, file.name);
    if (file.isDirectory()) {
      getAllJsFiles(filePath, fileList);
    } else if (file.name.endsWith('.js')) {
      fileList.push(filePath);
    }
  }
  return fileList;
}

const distDir = './dist';
const jsFiles = getAllJsFiles(distDir);

let totalFixed = 0;

for (const filePath of jsFiles) {
  let content = fs.readFileSync(filePath, 'utf-8');

  // Collect all unique node: modules required via esbuild's __require helper.
  const nodeModules = new Set();
  const requireRegex = /__require\d*\("(node:[^"]+)"\)/g;
  let match;
  while ((match = requireRegex.exec(content)) !== null) {
    nodeModules.add(match[1]);
  }

  if (nodeModules.size === 0) continue;

  // Build static import declarations and a lookup cache object.
  let imports = '';
  const mapping = {};
  let i = 0;
  for (const mod of nodeModules) {
    const varName = `__node_${mod.replace('node:', '').replace(/[^a-z0-9]/gi, '_')}_${i++}`;
    imports += `import * as ${varName} from '${mod}';\n`;
    mapping[mod] = varName;
  }

  imports += '\nconst __node_cache = {\n';
  for (const [mod, varName] of Object.entries(mapping)) {
    imports += `  '${mod}': ${varName},\n`;
  }
  imports += '};\n\n';

  // Replace every __require("node:…") call with a cache lookup.
  content = content.replace(/__require(\d*)\("(node:[^"]+)"\)/g, (_match, _num, mod) => {
    return `__node_cache['${mod}']`;
  });

  // Prepend the import block.
  content = imports + content;

  fs.writeFileSync(filePath, content, 'utf-8');
  console.log(`✓ Fixed ${nodeModules.size} node: import(s) in ${relative(distDir, filePath)}`);
  totalFixed++;
}

if (totalFixed === 0) {
  console.log('No __require node: calls found — nothing to patch.');
} else {
  console.log(`✓ Post-processing complete (${totalFixed} file(s) patched).`);
}
