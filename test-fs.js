import { readFile, readFileSync } from 'node:fs';

export default {
  async fetch(request) {
    return new Response(readFileSync('./test-fs.js', 'utf-8'));
  }
};