import { Container, getContainer } from "@cloudflare/containers";

// Container wrapper class
export class ContainerWorker extends Container {
  defaultPort = 8080;
  sleepAfter = "30m";
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    
    // Health check endpoint
    if (url.pathname === '/health' || url.pathname === '/_health') {
      try {
        const containerId = 'default';
        const id = env.CONTAINER_WORKER.idFromName(containerId);
        const stub = env.CONTAINER_WORKER.get(id);
        
        // Make a simple GET request to the root path to verify container is responsive
        const healthRequest = new Request('http://localhost/', {
          method: 'GET',
          headers: {
            'X-Health-Check': 'true'
          }
        });
        
        const response = await stub.fetch(healthRequest);
        
        // Container is ready if it responds (even with an error from the benchmark handler)
        // A 500 from the handler means the container is running, just not a valid benchmark request
        if (response.status >= 200 && response.status < 600) {
          return new Response('OK', { status: 200 });
        } else {
          return new Response(JSON.stringify({
            error: 'Container not responding',
            status: response.status
          }), {
            status: 503,
            headers: { 'Content-Type': 'application/json' }
          });
        }
        
      } catch (error) {
        return new Response(JSON.stringify({
          error: 'Container failed to start',
          details: error.message,
          stack: error.stack
        }), {
          status: 503,
          headers: { 'Content-Type': 'application/json' }
        });
      }
    }
    
    try {
      // Handle NoSQL proxy requests - intercept BEFORE forwarding to container
      if (url.pathname.startsWith('/nosql/')) {
        return await handleNoSQLRequest(request, env);
      }
      
      // Handle R2 proxy requests - intercept BEFORE forwarding to container
      if (url.pathname.startsWith('/r2/')) {
        return await handleR2Request(request, env);
      }
      
      // Get or create container instance
      const containerId = request.headers.get('x-container-id') || 'default';
      const id = env.CONTAINER_WORKER.idFromName(containerId);
      const stub = env.CONTAINER_WORKER.get(id);
      
      // Clone request and add Worker URL as header so container knows where to proxy R2 requests
      const modifiedRequest = new Request(request);
      modifiedRequest.headers.set('X-Worker-URL', url.origin);
      
      // Forward the request to the container
      return await stub.fetch(modifiedRequest);
      
    } catch (error) {
      console.error('Worker error:', error);
      
      const errorMessage = error.message || String(error);
      
      // Handle container not ready errors with 503
      if (errorMessage.includes('Container failed to start') || 
          errorMessage.includes('no container instance') ||
          errorMessage.includes('Durable Object') ||
          errorMessage.includes('provisioning')) {
        
        return new Response(JSON.stringify({
          error: 'Container failed to start',
          details: 'there is no container instance that can be provided to this durable object',
          message: errorMessage
        }), {
          status: 503,
          headers: { 'Content-Type': 'application/json' }
        });
      }
      
      // Other errors get 500
      return new Response(JSON.stringify({
        error: 'Internal server error',
        details: errorMessage,
        stack: error.stack
      }), {
        status: 500,
        headers: { 'Content-Type': 'application/json' }
      });
    }
  }
};

/**
 * Handle NoSQL (KV namespace) requests proxied from the container
 * Routes:
 *  - POST /nosql/insert - insert item
 *  - POST /nosql/update - update item
 *  - POST /nosql/get - get item
 *  - POST /nosql/query - query items
 *  - POST /nosql/delete - delete item
 */
async function handleNoSQLRequest(request, env) {
  try {
    const url = new URL(request.url);
    const operation = url.pathname.split('/').pop();
    
    // Parse request body
    const params = await request.json();
    const { table_name, primary_key, secondary_key, secondary_key_name, data } = params;
    
    const table = env[table_name];
    if (!table || typeof table.get !== 'function' || typeof table.put !== 'function') {
      return new Response(JSON.stringify({
        error: `KV namespace binding '${table_name}' not found`
      }), {
        status: 500,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    const indexKey = `__sebs_idx__${primary_key[1]}`;
    const readIndex = async () => {
      const raw = await table.get(indexKey);
      if (!raw) {
        return [];
      }
      try {
        const parsed = JSON.parse(raw);
        return Array.isArray(parsed) ? parsed : [];
      } catch {
        return [];
      }
    };
    const writeIndex = async (values) => {
      await table.put(indexKey, JSON.stringify(values));
    };

    const prefix = `${primary_key[1]}#`;

    let result;
    switch (operation) {
      case 'insert': {
        const compositeKey = `${primary_key[1]}#${secondary_key[1]}`;
        const keyData = { ...data };
        keyData[primary_key[0]] = primary_key[1];
        keyData[secondary_key[0]] = secondary_key[1];
        await table.put(compositeKey, JSON.stringify(keyData));
        const index = await readIndex();
        if (!index.includes(secondary_key[1])) {
          index.push(secondary_key[1]);
          await writeIndex(index);
        }
        result = { success: true };
        break;
      }
      case 'update': {
        const compositeKey = `${primary_key[1]}#${secondary_key[1]}`;
        const existingRaw = await table.get(compositeKey);
        let existing = {};
        if (existingRaw) {
          try {
            existing = JSON.parse(existingRaw);
          } catch {
            existing = {};
          }
        }
        const merged = { ...existing, ...data };
        merged[primary_key[0]] = primary_key[1];
        merged[secondary_key[0]] = secondary_key[1];
        await table.put(compositeKey, JSON.stringify(merged));
        const index = await readIndex();
        if (!index.includes(secondary_key[1])) {
          index.push(secondary_key[1]);
          await writeIndex(index);
        }
        result = { success: true };
        break;
      }
      case 'get': {
        const compositeKey = `${primary_key[1]}#${secondary_key[1]}`;
        const raw = await table.get(compositeKey);
        if (raw === null) {
          result = { data: null };
        } else {
          try {
            result = { data: JSON.parse(raw) };
          } catch {
            result = { data: raw };
          }
        }
        break;
      }
      case 'query': {
        let secondaryKeys = await readIndex();
        if (secondaryKeys.length === 0) {
          const list = await table.list({ prefix });
          secondaryKeys = (list.keys || []).map((k) => k.name.split('#').slice(1).join('#'));
        }
        const items = [];
        for (const secondaryValue of secondaryKeys) {
          const raw = await table.get(`${primary_key[1]}#${secondaryValue}`);
          if (raw === null) {
            continue;
          }
          try {
            items.push(JSON.parse(raw));
          } catch {
            items.push(raw);
          }
        }
        result = { items };
        break;
      }
      case 'delete': {
        const compositeKey = `${primary_key[1]}#${secondary_key[1]}`;
        await table.delete(compositeKey);
        const index = await readIndex();
        const next = index.filter((v) => v !== secondary_key[1]);
        if (next.length !== index.length) {
          await writeIndex(next);
        }
        result = { success: true };
        break;
      }
      default:
        return new Response(JSON.stringify({
          error: 'Unknown NoSQL operation'
        }), {
          status: 404,
          headers: { 'Content-Type': 'application/json' }
        });
    }
    
    return new Response(JSON.stringify(result || {}), {
      headers: { 'Content-Type': 'application/json' }
    });
    
  } catch (error) {
    console.error('NoSQL proxy error:', error);
    return new Response(JSON.stringify({
      error: error.message,
      stack: error.stack
    }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}

/**
 * Handle R2 storage requests proxied from the container
 * Routes:
 *  - GET /r2/download?bucket=X&key=Y - download object
 *  - POST /r2/upload?bucket=X&key=Y - upload object (body contains data)
 */
async function handleR2Request(request, env) {
  try {
    const url = new URL(request.url);
    const bucket = url.searchParams.get('bucket');
    const key = url.searchParams.get('key');
    
    // Check if R2 binding exists
    if (!env.R2) {
      return new Response(JSON.stringify({
        error: 'R2 binding not configured'
      }), {
        status: 500,
        headers: { 'Content-Type': 'application/json' }
      });
    }
    
    if (url.pathname === '/r2/list') {
      // List objects in R2 with a prefix (only needs bucket)
      if (!bucket) {
        return new Response(JSON.stringify({
          error: 'Missing bucket parameter'
        }), {
          status: 400,
          headers: { 'Content-Type': 'application/json' }
        });
      }
      
      try {
        const prefix = url.searchParams.get('prefix') || '';
        const list_res = await env.R2.list({ prefix });
        
        return new Response(JSON.stringify({
          objects: list_res.objects || []
        }), {
          headers: { 'Content-Type': 'application/json' }
        });
      } catch (error) {
        console.error('[worker.js /r2/list] Error:', error);
        return new Response(JSON.stringify({
          error: error.message
        }), {
          status: 500,
          headers: { 'Content-Type': 'application/json' }
        });
      }
    }
    
    // Multipart upload routes only need 'key' (bucket is implicit in the R2 binding)
    if (url.pathname === '/r2/multipart-init') {
      // Initiate a multipart upload; returns { key, uploadId }
      const contentType = url.searchParams.get('contentType') || 'application/octet-stream';
      console.log(`[worker.js /r2/multipart-init] key=${key}, contentType=${contentType}`);
      const multipart = await env.R2.createMultipartUpload(key, {
        httpMetadata: { contentType }
      });
      console.log(`[worker.js /r2/multipart-init] uploadId=${multipart.uploadId}`);
      return new Response(JSON.stringify({
        key: multipart.key,
        uploadId: multipart.uploadId
      }), { headers: { 'Content-Type': 'application/json' } });

    } else if (url.pathname === '/r2/multipart-part') {
      // Upload one part; returns { partNumber, etag }
      const uploadId = url.searchParams.get('uploadId');
      const partNumber = parseInt(url.searchParams.get('partNumber'), 10);
      console.log(`[worker.js /r2/multipart-part] key=${key}, uploadId=${uploadId}, partNumber=${partNumber}`);
      const multipart = env.R2.resumeMultipartUpload(key, uploadId);
      const part = await multipart.uploadPart(partNumber, request.body);
      console.log(`[worker.js /r2/multipart-part] uploaded part ${part.partNumber}, etag=${part.etag}`);
      return new Response(JSON.stringify({
        partNumber: part.partNumber,
        etag: part.etag
      }), { headers: { 'Content-Type': 'application/json' } });

    } else if (url.pathname === '/r2/multipart-complete') {
      // Complete a multipart upload; body is JSON { parts: [{ partNumber, etag }] }
      const uploadId = url.searchParams.get('uploadId');
      console.log(`[worker.js /r2/multipart-complete] key=${key}, uploadId=${uploadId}`);
      const { parts } = await request.json();
      const multipart = env.R2.resumeMultipartUpload(key, uploadId);
      const obj = await multipart.complete(parts);
      console.log(`[worker.js /r2/multipart-complete] completed, size=${obj ? obj.size : '?'}`);
      return new Response(JSON.stringify({ key: key }), {
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // Download and upload require a key (bucket is implicit in the R2 binding)
    if (!key) {
      return new Response(JSON.stringify({
        error: 'Missing key parameter'
      }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    if (url.pathname === '/r2/download') {
      const object = await env.R2.get(key);
      
      if (!object) {
        return new Response(JSON.stringify({
          error: 'Object not found'
        }), {
          status: 404,
          headers: { 'Content-Type': 'application/json' }
        });
      }
      
      // Return the object data
      return new Response(object.body, {
        headers: {
          'Content-Type': object.httpMetadata?.contentType || 'application/octet-stream',
          'Content-Length': object.size.toString()
        }
      });
      
    } else if (url.pathname === '/r2/upload') {
      // Upload to R2 — stream request.body directly to avoid buffering large payloads in Worker memory
      console.log(`[worker.js /r2/upload] bucket=${bucket}, key=${key}`);
      console.log(`[worker.js /r2/upload] env.R2 exists:`, !!env.R2);
      const contentLength = request.headers.get('Content-Length');
      console.log(`[worker.js /r2/upload] Content-Length: ${contentLength}`);
      
      // Use the key as-is (container already generates unique keys if needed)
      try {
        const putResult = await env.R2.put(key, request.body, {
          httpMetadata: { contentType: request.headers.get('Content-Type') || 'application/octet-stream' }
        });
        const size = putResult ? putResult.size : '(unknown)';
        console.log(`[worker.js /r2/upload] R2.put() succeeded, size=${size}`);
        console.log(`[worker.js /r2/upload] Successfully uploaded to R2 with key=${key}`);
      } catch (error) {
        console.error(`[worker.js /r2/upload] R2.put() error:`, error);
        throw error;
      }
      
      return new Response(JSON.stringify({
        key: key
      }), {
        headers: { 'Content-Type': 'application/json' }
      });
      
    } else {
      return new Response(JSON.stringify({
        error: 'Unknown R2 operation'
      }), {
        status: 404,
        headers: { 'Content-Type': 'application/json' }
      });
    }
    
  } catch (error) {
    console.error('R2 proxy error:', error);
    return new Response(JSON.stringify({
      error: error.message,
      stack: error.stack
    }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}

/**
 * Generate unique key for uploaded files
 */
function generateUniqueKey(key) {
  const parts = key.split('.');
  const ext = parts.length > 1 ? '.' + parts.pop() : '';
  const name = parts.join('.');
  const uuid = crypto.randomUUID().split('-')[0];
  return `${name}.${uuid}${ext}`;
}
