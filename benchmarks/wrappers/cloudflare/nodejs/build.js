/**
 * build.js — Convert a Node.js benchmark into a Cloudflare Workers-compatible bundle.
 *
 * Why this exists:
 *   Cloudflare Workers do not ship a Node.js runtime or a filesystem at deploy
 *   time: there is no `node_modules` directory, no `require()` resolution, and
 *   only a curated subset of Node built-ins is available (and only when opted
 *   in via the `node:` prefix and the `nodejs_compat` compatibility flag).
 *   Our SeBS benchmarks, however, are authored as regular Node.js code. This
 *   script bridges that gap by bundling the benchmark + its dependencies into
 *   a single ESM module that the Workers runtime can load.
 *
 * High-level pipeline:
 *   1. Discover source files under the wrapper directory (skipping tests,
 *      node_modules, dotfiles, and the previous build output).
 *   2. Run esbuild on every JS/TS entry point with a Workers-friendly config
 *      (ESM output, neutral platform, ES2020 target, tree-shaking).
 *   3. Apply the `nodeBuiltinsPlugin` to rewrite imports so that:
 *        - Node built-ins always use the `node:` prefix required by Workers.
 *        - `cloudflare:*` imports stay external (resolved by the runtime).
 *        - The legacy `request` npm module is swapped for a fetch-based
 *          polyfill, since it cannot run under Workers.
 *   4. Copy any non-code assets (templates, SQL, etc.) into `dist/` unchanged.
 */

const { build } = require('esbuild');
const fs = require('fs');
const { join, extname, dirname, relative } = require('path');

// Recursively collect every file that should be part of the Workers bundle.
// Excludes test directories, node_modules, build artifacts, and this script
// itself so that only benchmark sources and the wrapper code get processed.
function getAllFiles(dir, fileList = []) {
  const files = fs.readdirSync(dir, { withFileTypes: true });
  for (const file of files) {
    const filePath = join(dir, file.name);
    if (file.isDirectory()) {
      if (file.name !== 'node_modules' &&
          file.name !== 'test' &&
          file.name !== 'tests' &&
          file.name !== '__tests__' &&
          file.name !== 'dist' &&
          !file.name.startsWith('.')) {
        getAllFiles(filePath, fileList);
      }
    } else {
      if (!file.name.includes('.test.') &&
          !file.name.includes('.spec.') &&
          file.name !== 'build.js' &&
          file.name !== 'wrangler.toml') {
        fileList.push(filePath);
      }
    }
  }
  return fileList;
}

function copyFile(src, dest) {
  const destDir = dirname(dest);
  if (!fs.existsSync(destDir)) {
    fs.mkdirSync(destDir, { recursive: true });
  }
  fs.copyFileSync(src, dest);
}

// esbuild plugin that rewrites module imports so the output works on the
// Cloudflare Workers runtime. Workers only accept Node built-ins via the
// `node:` prefix (with the `nodejs_compat` flag enabled on the Worker), do
// not support arbitrary npm packages that rely on Node's networking stack,
// and resolve their own `cloudflare:*` imports at runtime.
const nodeBuiltinsPlugin = {
  name: 'node-builtins-external',
  setup(build) {
    const { resolve } = require('path');

    // Imports already using the `node:` or `cloudflare:` prefix are provided
    // by the Workers runtime itself — leave them external so esbuild does not
    // try to bundle them (which would fail, since they are not on disk).
    build.onResolve({ filter: /^(node:|cloudflare:)/ }, (args) => {
      return { path: args.path, external: true };
    });

    // Benchmarks commonly `require('fs')`, `require('path')`, etc. Workers
    // reject those bare specifiers; rewrite them to the `node:`-prefixed
    // form and mark them external so the runtime resolves them.
    build.onResolve({ filter: /^(fs|querystring|path|crypto|stream|buffer|util|events|http|https|net|tls|zlib|os|child_process|tty|assert|url|constants)$/ }, (args) => {
      return { path: 'node:' + args.path, external: true };
    });

    // The `request` npm module depends on Node's http/https clients and is
    // incompatible with Workers. Redirect every `require('request')` to our
    // fetch-based shim so benchmark code can keep the same call sites.
    build.onResolve({ filter: /^request$/ }, (args) => {
      const wrapperDir = __dirname;
      return {
        path: resolve(wrapperDir, 'request-polyfill.js')
      };
    });

    // `graceful-fs` monkey-patches the `fs` module at runtime, which Workers
    // rejects ("object is not extensible"). Redirect it straight to node:fs
    // so the patching never runs and consumers get the same API.
    build.onResolve({ filter: /^graceful-fs$/ }, () => {
      return { path: 'node:fs', external: true };
    });
  }
};


async function customBuild() {
  const srcDir = './';
  const outDir = './dist';

  // Start from a clean output directory so stale artifacts from a previous
  // build cannot leak into the Worker upload.
  if (fs.existsSync(outDir)) {
    fs.rmSync(outDir, { recursive: true });
  }
  fs.mkdirSync(outDir, { recursive: true });

  try {
    const files = getAllFiles(srcDir);

    // Split discovered files: code goes through esbuild, everything else
    // (JSON fixtures, templates, SQL, binary assets, ...) is copied verbatim.
    const jsFiles = files.filter(f =>
      ['.js', '.ts', '.jsx', '.tsx'].includes(extname(f))
    );

    const otherFiles = files.filter(f =>
      !['.js', '.ts', '.jsx', '.tsx'].includes(extname(f))
    );

    console.log('Building JS files:', jsFiles);

    if (jsFiles.length > 0) {
      // esbuild options chosen for Workers compatibility:
      //   - format: 'esm'          Workers modules must be ES modules.
      //   - platform: 'neutral'    Avoid Node- or browser-specific resolution;
      //                            the plugin above handles Node built-ins
      //                            explicitly.
      //   - target: 'es2020'       Matches the V8 version used by Workers.
      //   - bundle + treeShaking   Flattens dependencies into one module and
      //                            drops dead code to stay under Workers'
      //                            script size limit.
      //   - define.__dirname       Node's `__dirname` does not exist in
      //                            Workers; stub it with a harmless constant
      //                            so benchmark code that references it still
      //                            compiles.
      //   - define.global          Workers expose `globalThis` rather than
      //                            `global`; alias the two for compatibility.
      await build({
        entryPoints: jsFiles,
        bundle: true,
        format: 'esm',
        outdir: outDir,
        outbase: srcDir,
        platform: 'neutral',
        target: 'es2020',
        sourcemap: true,
        allowOverwrite: true,
        plugins: [nodeBuiltinsPlugin],
        define: {
          'process.env.NODE_ENV': '"production"',
          'global': 'globalThis',
          '__dirname': '"/bundle"'
        },
        mainFields: ['module', 'main'],
        treeShaking: true,
      });
    }

    // Non-code assets (e.g. HTML/CSS templates, JSON payloads) need to ship
    // alongside the bundle at their original relative paths so the worker
    // can read them via the runtime's asset APIs.
    for (const file of otherFiles) {
      const relativePath = relative(srcDir, file);
      const destPath = join(outDir, relativePath);
      copyFile(file, destPath);
      console.log(`Copied: ${relativePath}`);
    }

    console.log('✓ Build completed successfully');
  } catch (error) {
    console.error('Build failed:', error);
    process.exit(1);
  }
}

customBuild();