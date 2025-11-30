const { build } = require('esbuild');
const fs = require('fs');
const { join, extname, dirname, relative } = require('path');

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

const nodeBuiltinsPlugin = {
  name: 'node-builtins-external',
  setup(build) {
    // Keep node: prefixed modules external
    build.onResolve({ filter: /^(node:|cloudflare:)/ }, (args) => {
      return { path: args.path, external: true };
    });
    
    // Map bare node built-in names to node: versions and keep external
    build.onResolve({ filter: /^(fs|querystring|path|crypto|stream|buffer|util|events|http|https|net|tls|zlib|os|child_process|tty|assert|url)$/ }, (args) => {
      return { path: 'node:' + args.path, external: true };
    });
  }
};

const asyncNosqlPlugin = {
  name: 'async-nosql-transformer',
  setup(build) {
    // Transform function.js to make it async-compatible
    build.onLoad({ filter: /function\.js$/ }, async (args) => {
      let contents = await fs.promises.readFile(args.path, 'utf8');
      
      // Only transform if file uses nosql
      if (!contents.includes('nosqlClient')) {
        return { contents, loader: 'js' };
      }
      
      console.log('🔧 Transforming function.js for async nosql...');
      
      // Step 1: Add await before nosqlClient method calls
      contents = contents.replace(/(\s*)((?:const|let|var)\s+\w+\s*=\s*)?nosqlClient\.(insert|get|update|query|delete)\s*\(/g, 
        '$1$2await nosqlClient.$3(');
      
      // Step 2: Make all function declarations async (but not function expressions)
      contents = contents.replace(/^(\s*)function\s+(\w+)\s*\(/gm, '$1async function $2(');
      
      // Step 3: Add await before user-defined function calls
      // Process line by line to handle specific patterns
      const lines = contents.split('\n');
      const transformedLines = lines.map(line => {
        // Skip lines with function declarations or function expressions
        if (line.match(/\bfunction\s+\w+\s*\(/) || line.match(/=\s*(async\s+)?function\s*\(/)) {
          return line;
        }
        
        // Add await before function calls that look like user-defined functions
        // Match: identifier followed by ( where identifier starts line or follows whitespace/operators
        // but NOT if preceded by = (assignment), . (method call), or keywords
        line = line.replace(/(^|\s+|;|,|\()((?:const|let|var)\s+\w+\s*=\s*)?(\w+)\s*\(/g, (match, prefix, assignment, funcName) => {
          // Skip control flow keywords
          const controlFlow = ['if', 'for', 'while', 'switch', 'catch', 'return'];
          if (controlFlow.includes(funcName)) {
            return match;
          }
          
          // Skip built-in JavaScript functions and methods
          const builtins = ['console', 'require', 'push', 'join', 'split', 
                           'map', 'filter', 'reduce', 'forEach', 'find', 'findIndex',
                           'some', 'every', 'includes', 'parseInt', 'parseFloat', 
                           'isNaN', 'Array', 'Object', 'String', 'Number', 'Boolean',
                           'Math', 'JSON', 'Date', 'RegExp', 'Error', 'Promise'];
          if (builtins.includes(funcName)) {
            return match;
          }
          
          // Add await for everything else
          return `${prefix}${assignment || ''}await ${funcName}(`;
        });
        
        return line;
      });
      contents = transformedLines.join('\n');
      
      console.log('✓ Transformed function.js for async nosql');
      
      return {
        contents,
        loader: 'js',
      };
    });
  }
};

async function customBuild() {
  const srcDir = './';
  const outDir = './dist';
  
  if (fs.existsSync(outDir)) {
    fs.rmSync(outDir, { recursive: true });
  }
  fs.mkdirSync(outDir, { recursive: true });
  
  try {
    const files = getAllFiles(srcDir);
    
    const jsFiles = files.filter(f => 
      ['.js', '.ts', '.jsx', '.tsx'].includes(extname(f))
    );
    
    const otherFiles = files.filter(f => 
      !['.js', '.ts', '.jsx', '.tsx'].includes(extname(f))
    );
    
    console.log('Building JS files:', jsFiles);
    
    if (jsFiles.length > 0) {
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
        plugins: [nodeBuiltinsPlugin, asyncNosqlPlugin],
        define: {
          'process.env.NODE_ENV': '"production"',
          'global': 'globalThis',
          '__dirname': '"/bundle"'
        },
        mainFields: ['module', 'main'],
        treeShaking: true,
      });
      
      // POST-PROCESS: Replace dynamic requires with static imports
      console.log('Post-processing to fix node: module imports...');
      
      for (const jsFile of jsFiles) {
        const outPath = join(outDir, relative(srcDir, jsFile));
        
        if (fs.existsSync(outPath)) {
          let content = fs.readFileSync(outPath, 'utf-8');
          
          // Find all node: modules being dynamically required
          const nodeModules = new Set();
          const requireRegex = /__require\d*\("(node:[^"]+)"\)/g;
          let match;
          while ((match = requireRegex.exec(content)) !== null) {
            nodeModules.add(match[1]);
          }
          
          if (nodeModules.size > 0) {
            // Generate static imports at the top
            let imports = '';
            const mapping = {};
            let i = 0;
            for (const mod of nodeModules) {
              const varName = `__node_${mod.replace('node:', '').replace(/[^a-z0-9]/gi, '_')}_${i++}`;
              imports += `import * as ${varName} from '${mod}';\n`;
              mapping[mod] = varName;
            }
            
            // Add cache object
            imports += '\nconst __node_cache = {\n';
            for (const [mod, varName] of Object.entries(mapping)) {
              imports += `  '${mod}': ${varName},\n`;
            }
            imports += '};\n\n';
            
            // Replace all __require calls with cache lookups
            content = content.replace(/__require(\d*)\("(node:[^"]+)"\)/g, (match, num, mod) => {
              return `__node_cache['${mod}']`;
            });
            
            // Prepend imports to the file
            content = imports + content;
            
            fs.writeFileSync(outPath, content, 'utf-8');
            console.log(`✓ Fixed ${nodeModules.size} node: imports in ${relative(srcDir, jsFile)}`);
          }
        }
      }
    }
    
    // Copy non-JS files (templates, etc.)
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