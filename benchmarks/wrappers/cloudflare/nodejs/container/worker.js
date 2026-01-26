import { Container, getContainer } from "@cloudflare/containers";
import { DurableObject } from "cloudflare:workers";

// Container wrapper class
export class ContainerWorker extends Container {
  defaultPort = 8080;
  sleepAfter = "30m";
}

// Durable Object for NoSQL storage (simple proxy to ctx.storage)
export class KVApiObject extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
  }

  async insert(key, value) {
    await this.ctx.storage.put(key.join(':'), value);
    return { success: true };
  }

  async update(key, value) {
    await this.ctx.storage.put(key.join(':'), value);
    return { success: true };
  }

  async get(key) {
    const value = await this.ctx.storage.get(key.join(':'));
    return { data: value || null };
  }

  async query(keyPrefix) {
    const list = await this.ctx.storage.list();
    const items = [];
    for (const [k, v] of list) {
      items.push(v);
    }
    return { items };
  }

  async delete(key) {
    await this.ctx.storage.delete(key.join(':'));
    return { success: true };
  }
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
 * Handle NoSQL (Durable Object) requests proxied from the container
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
    
    // Get Durable Object stub - table_name should match the DO class name
    if (!env[table_name]) {
      return new Response(JSON.stringify({
        error: `Durable Object binding '${table_name}' not found`
      }), {
        status: 500,
        headers: { 'Content-Type': 'application/json' }
      });
    }
    
    // Create DO ID from primary key
    const doId = env[table_name].idFromName(primary_key.join(':'));
    const doStub = env[table_name].get(doId);
    
    // Forward operation to Durable Object
    let result;
    switch (operation) {
      case 'insert':
        result = await doStub.insert(secondary_key, data);
        break;
      case 'update':
        result = await doStub.update(secondary_key, data);
        break;
      case 'get':
        result = await doStub.get(secondary_key);
        break;
      case 'query':
        result = await doStub.query(secondary_key_name);
        break;
      case 'delete':
        result = await doStub.delete(secondary_key);
        break;
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
    
    // All other R2 operations require both bucket and key
    if (!bucket || !key) {
      return new Response(JSON.stringify({
        error: 'Missing bucket or key parameter'
      }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' }
      });
    }
    
    if (url.pathname === '/r2/download') {
      // Download from R2
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
      // Upload to R2
      console.log(`[worker.js /r2/upload] bucket=${bucket}, key=${key}`);
      console.log(`[worker.js /r2/upload] env.R2 exists:`, !!env.R2);
      const data = await request.arrayBuffer();
      console.log(`[worker.js /r2/upload] Received ${data.byteLength} bytes`);
      
      // Use the key as-is (container already generates unique keys if needed)
      try {
        const putResult = await env.R2.put(key, data);
        console.log(`[worker.js /r2/upload] R2.put() returned:`, putResult);
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
