"""Cloudflare Workflows code generator.

Translates SeBS FSM definitions (definition.json) into TypeScript source code
for Cloudflare Workflows. Map and Parallel states fan out to child workflow
instances so Cloudflare can execute work concurrently across instances.
"""

import json
import re
from typing import Dict, List, Union

from sebs.faas.fsm import Generator, State, Task, Switch, Map, Parallel, Repeat, Loop


class CloudflareWorkflowGenerator(Generator):
    """Generate TypeScript Workflow code from FSM definitions."""

    def __init__(
        self,
        chunk_size: int = 1,
        max_instances: int = 1,
        dispatch_timeout_seconds: int = 300,
    ):
        """Initialize the Cloudflare Workflow generator.

        Args:
            chunk_size: Number of Map items assigned to one child ItemWorkflow.
            max_instances: Container ceiling configured in wrangler.toml.
            dispatch_timeout_seconds: Per-container dispatch timeout.
        """
        super().__init__()
        self._chunk_size = max(1, int(chunk_size))
        self._max_instances = max(1, int(max_instances))
        self._dispatch_timeout_ms = max(300_000, int(dispatch_timeout_seconds) * 1000)

    def generate(self) -> str:
        """Generate the complete TypeScript workflow source file."""
        cases = []
        for state in self._all_generated_states().values():
            case_code = self._encode_state_case(state)
            cases.append(case_code)

        cases.append(
            """\
      case "__end__": {
        if (_fanin) {
          const { parentId, stateName, branchIdx, total, branchRoot } = _fanin;
          await reportFanIn(this.env, {
            parentId,
            stateName,
            idx: branchIdx,
            total,
            mode: "object",
            key: branchRoot,
            result: state,
          });
        }
        return state;
      }"""
        )

        switch_body = "\n".join(cases)

        return f"""\
/*
 * Required wrangler bindings:
 * - WORKFLOW: Workflow binding for BenchmarkWorkflow
 * - ITEM_WORKFLOW: Workflow binding for ItemWorkflow
 * - FANIN: Durable Object namespace for FanInCoordinator
 * - DISPATCHER: Durable Object namespace for DispatcherContainer
 * - [[containers]] class_name = "DispatcherContainer", max_instances = {self._max_instances}
 */
export {{ ContainerProxy }} from "@cloudflare/containers";
import {{ Container }} from "@cloudflare/containers";
import {{ WorkflowEntrypoint, WorkflowEvent, WorkflowStep }} from "cloudflare:workers";

interface Env {{
  WORKFLOW: Workflow;
  ITEM_WORKFLOW: Workflow;
  FANIN: DurableObjectNamespace;
  DISPATCHER: DurableObjectNamespace;
  WORKFLOW_NAME?: string;
  REDIS_HOST?: string;
  REDIS_USERNAME?: string;
  REDIS_PASSWORD?: string;
  R2?: R2Bucket;
  [key: string]: any;
}}

function getDurableObjectByName(
  namespace: DurableObjectNamespace,
  name: string,
): DurableObjectStub {{
  return namespace.get(namespace.idFromName(name));
}}

function sleep(ms: number): Promise<void> {{
  return new Promise((resolve) => setTimeout(resolve, ms));
}}

function textSizeBytes(value: unknown): number {{
  return new TextEncoder().encode(JSON.stringify(value)).length;
}}

function errorMessage(error: unknown): string {{
  return error instanceof Error ? `${{error.name}}: ${{error.message}}` : String(error);
}}

async function reportFanIn(
  env: Env,
  report: {{
    parentId: string;
    stateName: string;
    idx: number;
    total: number;
    mode: "array" | "object";
    key: string | null;
    result: any;
    error?: string;
  }},
): Promise<void> {{
  const fanin = getDurableObjectByName(env.FANIN, `${{report.parentId}}-${{report.stateName}}`);
  await fanin.fetch("http://fanin/report", {{
    method: "POST",
    headers: {{ "Content-Type": "application/json" }},
    body: JSON.stringify(report),
  }});
}}

async function fetchWithTimeout(
  stub: DurableObjectStub,
  url: string,
  init: RequestInit,
  timeoutMs: number,
): Promise<Response> {{
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  try {{
    return await stub.fetch(url, {{ ...init, signal: controller.signal }});
  }} finally {{
    clearTimeout(timeoutId);
  }}
}}

function isRetryableFetchError(error: unknown): boolean {{
  const message = error instanceof Error ? error.message : String(error);
  return (
    message.includes("fetch failed") ||
    message.includes("Network connection lost") ||
    message.includes("internal error connecting to the port")
  );
}}

function isFetchTimeoutError(error: unknown): boolean {{
  const message = error instanceof Error ? error.message : String(error);
  return (
    message.includes("AbortError") ||
    message.includes("The operation was aborted") ||
    message.includes("timed out")
  );
}}

// Retry fetch on 502/503, timeout, or non-JSON responses.
// Any other non-2xx response is treated as a hard error and thrown immediately.
async function dispatchWithRetry(
  env: Env,
  containerId: string,
  workflowRequestId: string,
  body: any,
  maxAttempts = 10,
  timeoutMs = {self._dispatch_timeout_ms},
): Promise<any> {{
  const stub = getDurableObjectByName(env.DISPATCHER, containerId);
  console.log(
    `[workflow-dispatch] containerId=${{containerId}} function=${{body?.function ?? "unknown"}}`
  );
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {{
    let r: Response;
    const headers: Record<string, string> = {{
      "Content-Type": "application/json",
      "X-Dispatcher-Container-ID": containerId,
      "X-SEBS-Workflow-Request-ID": workflowRequestId,
    }};
    if (env.WORKFLOW_NAME) {{
      headers["X-SEBS-Workflow-Name"] = env.WORKFLOW_NAME;
    }}
    if (env.REDIS_HOST) {{
      headers["X-SEBS-REDIS-HOST"] = env.REDIS_HOST;
      if (env.REDIS_USERNAME) {{
        headers["X-SEBS-REDIS-USERNAME"] = env.REDIS_USERNAME;
      }}
      if (env.REDIS_PASSWORD) {{
        headers["X-SEBS-REDIS-PASSWORD"] = env.REDIS_PASSWORD;
      }}
    }}
    try {{
      r = await fetchWithTimeout(
        stub,
        "http://dispatcher/",
        {{
          method: "POST",
          headers,
          body: JSON.stringify(body),
        }},
        timeoutMs,
      );
    }} catch (error) {{
      if (isFetchTimeoutError(error)) {{
        throw new Error(
          `Dispatcher call timed out after ${{timeoutMs}}ms for ${{body?.function ?? "unknown"}} ` +
          `on containerId=${{containerId}}. ` +
          "Not retrying because the container may still be running."
        );
      }}
      if (attempt < maxAttempts && isRetryableFetchError(error)) {{
        await sleep(Math.min(5000 * attempt, 30000));
        continue;
      }}
      throw error;
    }}

    if (r.status === 503 || r.status === 502) {{
      await sleep(Math.min(5000 * attempt, 30000));
      continue;
    }}
    const text = await r.text();
    if (!r.ok) {{
      throw new Error(`Dispatcher returned HTTP ${{r.status}}: ${{text.slice(0, 200)}}`);
    }}
    try {{
      return JSON.parse(text);
    }} catch (_) {{
      if (attempt < maxAttempts) {{
        await sleep(Math.min(5000 * attempt, 30000));
        continue;
      }}
      throw new Error(
        `Dispatcher returned non-JSON after ${{maxAttempts}} attempts: ${{text.slice(0, 200)}}`
      );
    }}
  }}
  throw new Error(`Dispatcher unavailable after ${{maxAttempts}} attempts`);
}}

function isDuplicateWorkflowError(error: unknown): boolean {{
  const message = error instanceof Error ? error.message : String(error);
  return (
    message.includes("already exists") ||
    message.includes("duplicate") ||
    message.includes("conflict") ||
    message.includes("409")
  );
}}

function isRateLimitError(error: unknown): boolean {{
  const message = error instanceof Error ? error.message : String(error);
  return message.includes("429") || message.includes("rate limit");
}}

async function createWorkflowWithRetry(
  workflow: Workflow,
  id: string,
  params: any,
  maxAttempts = 10,
): Promise<void> {{
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {{
    try {{
      await workflow.create({{ id, params }});
      return;
    }} catch (error) {{
      if (isDuplicateWorkflowError(error)) {{
        return;
      }}
      if (attempt < maxAttempts && isRateLimitError(error)) {{
        await sleep(Math.min(5000 * attempt, 30000));
        continue;
      }}
      throw error;
    }}
  }}
}}

export class BenchmarkWorkflow extends WorkflowEntrypoint<Env, any> {{
  async run(event: WorkflowEvent<any>, step: WorkflowStep) {{
    let state: any = structuredClone(event.payload ?? {{}});
    const {{ _start, _fanin }} = state as any;
    delete (state as any)._start;
    delete (state as any)._fanin;
    let current = _start ?? {json.dumps(self.root.name)};
    const dispatchContainerId = _fanin
      ? `${{_fanin.parentId}}-${{_fanin.stateName}}-branch-${{_fanin.branchIdx}}`
      : event.instanceId;
    const workflowRequestId = _fanin?.workflowRequestId ?? event.instanceId;

    try {{
      while (true) {{
        switch (current) {{
{switch_body}
          default:
            throw new Error(`Unknown state: ${{current}}`);
        }}
      }}
    }} catch (error) {{
      if (_fanin) {{
        const {{ parentId, stateName, branchIdx, total, branchRoot }} = _fanin;
        const message = errorMessage(error);
        console.log(
          `[workflow-branch-error] parentId=${{parentId}} state=${{stateName}} ` +
          `branchIdx=${{branchIdx}} root=${{branchRoot}} error=${{message}}`
        );
        await reportFanIn(this.env, {{
          parentId,
          stateName,
          idx: branchIdx,
          total,
          mode: "object",
          key: branchRoot,
          result: null,
          error: message,
        }});
      }}
      throw error;
    }}
  }}
}}

export default {{
  async fetch(request: Request, env: Env): Promise<Response> {{
    const url = new URL(request.url);
    if (request.method === "GET" && url.searchParams.has("id")) {{
      const id = url.searchParams.get("id")!;
      const instance = await env.WORKFLOW.get(id);
      const status = await instance.status();
      return Response.json({{
        status: status.status,
        output: (status as any).output ?? null,
        error: (status as any).error ?? null,
      }});
    }}
    const payload = await request.json();
    const instance = await env.WORKFLOW.create({{ params: payload }});
    return Response.json({{ id: instance.id }}, {{ status: 202 }});
  }},
}};

{self._emit_proxy_handlers()}

{self._emit_item_workflow()}

{self._emit_fanin_coordinator()}

{self._emit_dispatcher_container()}
"""

    def _all_generated_states(self) -> Dict[str, State]:
        """Return top-level and Parallel branch states in generation order."""
        states: Dict[str, State] = {}

        def add_state(state: State) -> None:
            """Add a state and nested parallel branch states once."""
            if state.name not in states:
                states[state.name] = state
            if isinstance(state, Parallel):
                for branch in state.branches:
                    branch_states = {n: State.deserialize(n, s) for n, s in branch.states.items()}
                    for branch_state in branch_states.values():
                        add_state(branch_state)

        for state in self.states.values():
            add_state(state)
        return states

    def _encode_state_case(self, state: State) -> str:
        """Encode a single FSM state as a switch case block."""
        if isinstance(state, Task):
            return self._encode_task_case(state)
        elif isinstance(state, Switch):
            return self._encode_switch_case(state)
        elif isinstance(state, Map):
            return self._encode_map_case(state)
        elif isinstance(state, Parallel):
            return self._encode_parallel_case(state)
        elif isinstance(state, Repeat):
            return self._encode_repeat_case(state)
        elif isinstance(state, Loop):
            return self._encode_loop_case(state)
        else:
            raise ValueError(f"Unknown state type: {type(state)}")

    def _encode_task_case(self, state: Task) -> str:
        """Encode a Task state as a step.do() call."""
        next_state = f'"{state.next}"' if state.next else '"__end__"'
        var = self._js_identifier(state.name)

        is_terminal = next_state == '"__end__"'
        if is_terminal:
            merge_expr = f"{var}_result"
        else:
            merge_expr = (
                f'(typeof {var}_result === "object" && {var}_result !== null'
                f" && !Array.isArray({var}_result))"
                f"\n            ? {{...state, ...{var}_result}} : {var}_result"
            )

        if state.failure:
            return f"""\
      case "{state.name}": {{
        try {{
          const {var}_result = await step.do("{state.name}", async () => {{
            return await dispatchWithRetry(
              this.env,
              dispatchContainerId,
              workflowRequestId,
              {{
              function: {json.dumps(state.func_name)},
              input: state,
              }},
            );
          }});
          state = {merge_expr};
          current = {next_state};
        }} catch (e) {{
          state = {{ ...state, _error: String(e) }};
          current = "{state.failure}";
        }}
        break;
      }}"""
        else:
            return f"""\
      case "{state.name}": {{
        const {var}_result = await step.do("{state.name}", async () => {{
          return await dispatchWithRetry(
            this.env,
            dispatchContainerId,
            workflowRequestId,
            {{
            function: {json.dumps(state.func_name)},
            input: state,
            }},
          );
        }});
        state = {merge_expr};
        current = {next_state};
        break;
      }}"""

    def _encode_switch_case(self, state: Switch) -> str:
        """Encode a Switch state as if/else conditions."""
        conditions = []
        for case in state.cases:
            var_path = self._js_var_path("state", case.var)
            op = case.op
            val = case.val if isinstance(case.val, (int, float)) else json.dumps(case.val)
            conditions.append(f'        if ({var_path} {op} {val}) {{ current = "{case.next}"; }}')

        default = state.default if state.default else "__end__"
        else_clause = f'        else {{ current = "{default}"; }}'

        if len(conditions) > 1:
            lines = [conditions[0]]
            for condition in conditions[1:]:
                lines.append("        else " + condition.strip())
            lines.append(else_clause)
            body = "\n".join(lines)
        else:
            body = conditions[0] + "\n" + else_clause

        return f"""\
      case "{state.name}": {{
{body}
        break;
      }}"""

    def _encode_map_case(self, state: Map) -> str:
        """Encode a Map state as ItemWorkflow fan-out with Durable Object fan-in."""
        next_state = f'"{state.next}"' if state.next else '"__end__"'
        var = self._js_identifier(state.name)
        array_path = self._js_var_path("state", state.array)
        input_expr = self._map_item_input_expr(state, "state")
        func_name = self._map_func_name(state)

        return f"""\
      case "{state.name}": {{
        const parentId_{var} = event.instanceId;
        const mapInputs_{var} = {array_path}.map((item: any) => {input_expr});
        const totalChunks_{var} = await step.do("{state.name}_spawn", async () => {{
          const total = Math.ceil(mapInputs_{var}.length / {self._chunk_size});
          console.log(
            `[workflow-map-spawn] parentId=${{parentId_{var}}} state={state.name} ` +
            `items=${{mapInputs_{var}.length}} chunks=${{total}} chunkSize={self._chunk_size}`
          );
          await Promise.all(
            Array.from({{ length: total }}, async (_unused: unknown, chunkIdx: number) => {{
              const start = chunkIdx * {self._chunk_size};
              const childId = `${{parentId_{var}}}-{state.name}-${{chunkIdx}}`;
              console.log(
                `[workflow-map-child] parentId=${{parentId_{var}}} state={state.name} ` +
                `chunkIdx=${{chunkIdx}} childId=${{childId}}`
              );
              await createWorkflowWithRetry(this.env.ITEM_WORKFLOW, childId, {{
                items: mapInputs_{var}.slice(start, start + {self._chunk_size}),
                parentId: parentId_{var},
                workflowRequestId,
                stateName: "{state.name}",
                chunkIdx,
                total,
                func: {json.dumps(func_name)},
              }});
            }})
          );
          return total;
        }});
        if (totalChunks_{var} === 0) {{
          {array_path} = [];
        }} else {{
          const done_{var} = await step.waitForEvent("{state.name}_done", {{
            type: `{state.name}-complete-${{parentId_{var}}}`,
            timeout: "2 hours",
          }});
          const payload_{var} = (done_{var} as any).payload;
          if (payload_{var}.error) {{
            throw new Error(`Map state {state.name} failed: ${{payload_{var}.error}}`);
          }}
          {array_path} = payload_{var}.results;
        }}
        current = {next_state};
        break;
      }}"""

    def _encode_parallel_case(self, state: Parallel) -> str:
        """Encode a Parallel state as BenchmarkWorkflow child-instance fan-out."""
        next_state = f'"{state.next}"' if state.next else '"__end__"'
        var = self._js_identifier(state.name)
        total = len(state.branches)
        spawn_lines = []
        for idx, branch in enumerate(state.branches):
            spawn_lines.append(
                f"""\
            (async () => {{
              const childId = `${{parentId_{var}}}-{state.name}-branch-{idx}`;
              console.log(
                `[workflow-parallel-child] parentId=${{parentId_{var}}} ` +
                `state={state.name} branchIdx={idx} root={branch.root} childId=${{childId}}`
              );
              await createWorkflowWithRetry(
                this.env.WORKFLOW,
                childId,
                {{
                ...state,
                _start: {json.dumps(branch.root)},
                _fanin: {{
                  parentId: parentId_{var},
                  workflowRequestId,
                  stateName: "{state.name}",
                  branchIdx: {idx},
                  total: {total},
                  branchRoot: {json.dumps(branch.root)},
                }},
                }},
              );
            }})()"""
            )
        spawn_body = ",\n".join(spawn_lines)

        return f"""\
      case "{state.name}": {{
        const parentId_{var} = event.instanceId;
        await step.do("{state.name}_spawn", async () => {{
          console.log(
            `[workflow-parallel-spawn] parentId=${{parentId_{var}}} ` +
            `state={state.name} branches={total}`
          );
          await Promise.all([
{spawn_body},
          ]);
        }});
        const done_{var} = await step.waitForEvent("{state.name}_done", {{
          type: `{state.name}-complete-${{parentId_{var}}}`,
          timeout: "2 hours",
        }});
        const payload_{var} = (done_{var} as any).payload;
        if (payload_{var}.error) {{
          throw new Error(`Parallel state {state.name} failed: ${{payload_{var}.error}}`);
        }}
        state = {{ ...state, ...payload_{var}.results }};
        current = {next_state};
        break;
      }}"""

    def _encode_repeat_case(self, state: Repeat) -> str:
        """Encode a Repeat state as a counted sequential loop."""
        next_state = f'"{state.next}"' if state.next else '"__end__"'
        return f"""\
      case "{state.name}": {{
        for (let i = 0; i < {state.count}; i++) {{
          state = await step.do(`{state.name}_${{i}}`, async () => {{
            return await dispatchWithRetry(
              this.env,
              dispatchContainerId,
              workflowRequestId,
              {{
              function: {json.dumps(state.func_name)},
              input: state,
              }},
            );
          }});
        }}
        current = {next_state};
        break;
      }}"""

    def _encode_loop_case(self, state: Loop) -> str:
        """Encode a Loop state as a sequential for loop over an array."""
        next_state = f'"{state.next}"' if state.next else '"__end__"'
        array_path = self._js_var_path("state", state.array)

        return f"""\
      case "{state.name}": {{
        for (let i = 0; i < {array_path}.length; i++) {{
          {array_path}[i] = await step.do(`{state.name}_${{i}}`, async () => {{
            return await dispatchWithRetry(
              this.env,
              dispatchContainerId,
              workflowRequestId,
              {{
              function: {json.dumps(state.func_name)},
              input: {array_path}[i],
              }},
            );
          }});
        }}
        current = {next_state};
        break;
      }}"""

    def _emit_item_workflow(self) -> str:
        """Emit the child workflow that runs one Map chunk."""
        return """\
export class ItemWorkflow extends WorkflowEntrypoint<Env, any> {
  async run(event: WorkflowEvent<any>, step: WorkflowStep) {
    const { items, parentId, workflowRequestId, stateName, chunkIdx, total, func } = event.payload;
    console.log(
      `[workflow-item] parentId=${parentId} state=${stateName} ` +
      `chunkIdx=${chunkIdx} total=${total} func=${func} items=${items.length}`
    );
    try {
      const results = await step.do(`${stateName}_${chunkIdx}`, async () => {
        const containerId = `${parentId}-${stateName}-${chunkIdx}`;
        if (items.length === 1) {
          const result = await dispatchWithRetry(
            this.env,
            containerId,
            workflowRequestId ?? parentId,
            {
            function: func,
            input: items[0],
            },
          );
          return [result];
        }
        return await Promise.all(
          items.map((item: any) =>
            dispatchWithRetry(
              this.env,
              containerId,
              workflowRequestId ?? parentId,
              {
              function: func,
              input: item,
              },
            )
          )
        );
      });

      await reportFanIn(this.env, {
        parentId,
        stateName,
        idx: chunkIdx,
        total,
        mode: "array",
        key: null,
        result: results,
      });
      return results;
    } catch (error) {
      const message = errorMessage(error);
      console.log(
        `[workflow-item-error] parentId=${parentId} state=${stateName} ` +
        `chunkIdx=${chunkIdx} func=${func} error=${message}`
      );
      await reportFanIn(this.env, {
        parentId,
        stateName,
        idx: chunkIdx,
        total,
        mode: "array",
        key: null,
        result: null,
        error: message,
      });
      throw error;
    }
  }
}"""

    def _emit_proxy_handlers(self) -> str:
        """Emit R2 and KV proxy handlers used by containerized benchmark code."""
        return """\
async function handleNoSQLRequest(request: Request, env: Env): Promise<Response> {
  try {
    const url = new URL(request.url);
    const operation = url.pathname.split("/").pop();
    const params = await request.json() as any;
    const { table_name, primary_key, secondary_key, data } = params;
    const table = env[table_name];
    if (!table || typeof table.get !== "function" || typeof table.put !== "function") {
      return Response.json(
        { error: `KV namespace binding '${table_name}' not found` },
        { status: 500 },
      );
    }

    const indexKey = `__sebs_idx__${primary_key[1]}`;
    const readIndex = async (): Promise<string[]> => {
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
    const writeIndex = async (values: string[]) => {
      await table.put(indexKey, JSON.stringify(values));
    };

    const compositeKey = `${primary_key[1]}#${secondary_key?.[1]}`;
    let result: any;
    switch (operation) {
      case "insert": {
        const keyData = {
          ...data,
          [primary_key[0]]: primary_key[1],
          [secondary_key[0]]: secondary_key[1],
        };
        await table.put(compositeKey, JSON.stringify(keyData));
        const index = await readIndex();
        if (!index.includes(secondary_key[1])) {
          index.push(secondary_key[1]);
          await writeIndex(index);
        }
        result = { success: true };
        break;
      }
      case "update": {
        const existingRaw = await table.get(compositeKey);
        let existing = {};
        if (existingRaw) {
          try {
            existing = JSON.parse(existingRaw);
          } catch {
            existing = {};
          }
        }
        const merged = {
          ...existing,
          ...data,
          [primary_key[0]]: primary_key[1],
          [secondary_key[0]]: secondary_key[1],
        };
        await table.put(compositeKey, JSON.stringify(merged));
        const index = await readIndex();
        if (!index.includes(secondary_key[1])) {
          index.push(secondary_key[1]);
          await writeIndex(index);
        }
        result = { success: true };
        break;
      }
      case "get": {
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
      case "query": {
        const prefix = `${primary_key[1]}#`;
        let secondaryKeys = await readIndex();
        if (secondaryKeys.length === 0) {
          const list = await table.list({ prefix });
          secondaryKeys = (list.keys || []).map((k: any) =>
            k.name.split("#").slice(1).join("#")
          );
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
      case "delete": {
        await table.delete(compositeKey);
        const index = await readIndex();
        const next = index.filter((value) => value !== secondary_key[1]);
        if (next.length !== index.length) {
          await writeIndex(next);
        }
        result = { success: true };
        break;
      }
      default:
        return Response.json({ error: "Unknown NoSQL operation" }, { status: 404 });
    }
    return Response.json(result || {});
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return Response.json({ error: message }, { status: 500 });
  }
}

async function handleR2Request(request: Request, env: Env): Promise<Response> {
  try {
    const url = new URL(request.url);
    const key = url.searchParams.get("key");
    if (!env.R2) {
      return Response.json({ error: "R2 binding not configured" }, { status: 500 });
    }

    if (url.pathname === "/r2/list") {
      const prefix = url.searchParams.get("prefix") || "";
      const list = await env.R2.list({ prefix });
      return Response.json({ objects: list.objects || [] });
    }

    if (!key) {
      return Response.json({ error: "Missing key parameter" }, { status: 400 });
    }

    if (url.pathname === "/r2/download") {
      const rangeHeader = request.headers.get("Range");
      let options: any = undefined;
      let rangeStart: number | undefined;
      let rangeEnd: number | undefined;
      if (rangeHeader) {
        const match = rangeHeader.match(/^bytes=(\\d+)-(\\d+)$/);
        if (match) {
          rangeStart = Number(match[1]);
          rangeEnd = Number(match[2]);
          options = { range: { offset: rangeStart, length: rangeEnd - rangeStart + 1 } };
        }
      }
      const object = (await env.R2.get(key, options)) as R2ObjectBody | null;
      if (!object) {
        return Response.json({ error: "Object not found" }, { status: 404 });
      }
      const headers = new Headers();
      headers.set("Content-Type", object.httpMetadata?.contentType || "application/octet-stream");
      if (rangeHeader && rangeStart !== undefined && rangeEnd !== undefined) {
        headers.set("Content-Range", `bytes ${rangeStart}-${rangeEnd}/${object.size}`);
        headers.set("Content-Length", String(rangeEnd - rangeStart + 1));
        return new Response(object.body, { status: 206, headers });
      }
      headers.set("Content-Length", String(object.size ?? ""));
      return new Response(object.body, { headers });
    }

    if (url.pathname === "/r2/upload") {
      await env.R2.put(key, request.body!);
      return Response.json({ key });
    }

    return Response.json({ error: "Unknown R2 operation" }, { status: 404 });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return Response.json({ error: message }, { status: 500 });
  }
}"""

    def _emit_fanin_coordinator(self) -> str:
        """Emit the Durable Object that coordinates Map and Parallel fan-in."""
        return """\
export class FanInCoordinator {
  state: DurableObjectState;
  env: Env;

  constructor(state: DurableObjectState, env: Env) {
    this.state = state;
    this.env = env;
  }

  async fetch(request: Request): Promise<Response> {
    if (request.method !== "POST") {
      return new Response("Method not allowed", { status: 405 });
    }

    const report = await request.json() as {
      parentId: string;
      stateName: string;
      idx: number;
      total: number;
      mode: "array" | "object";
      key: string | null;
      result: any;
      error?: string;
    };
    const seenKey = `seen:${report.idx}`;
    const alreadySeen = await this.state.storage.get(seenKey);
    if (alreadySeen !== undefined) {
      return Response.json({ ok: true, duplicate: true });
    }

    await this.state.storage.put(seenKey, true);
    await this.state.storage.put(`result:${report.idx}`, {
      key: report.key,
      result: report.result,
      error: report.error,
    });

    const entries = await this.state.storage.list<{
      key: string | null;
      result: any;
      error?: string;
    }>({ prefix: "result:" });
    let assembledBytes = 0;
    for (const entry of entries.values()) {
      assembledBytes += textSizeBytes(entry.result);
      assembledBytes += textSizeBytes(entry.error ?? "");
    }
    if (assembledBytes > 900 * 1024) {
      throw new Error(
        "Fan-in payload exceeds 900 KiB - R2 reference path not yet implemented. " +
          "Reduce fan-out width or result size."
      );
    }

    if (entries.size === report.total) {
      const ordered = [...entries.entries()].sort(([a], [b]) => {
        const ai = Number(a.slice("result:".length));
        const bi = Number(b.slice("result:".length));
        return ai - bi;
      });
      const failed = ordered.find(([_idx, entry]) => entry.error);
      let results: any;
      let error: string | undefined;
      if (failed) {
        const [failedIdx, entry] = failed;
        error = `${report.stateName}[${failedIdx.slice("result:".length)}]: ${entry.error}`;
      } else if (report.mode === "array") {
        results = [];
        for (const [_idx, entry] of ordered) {
          results.push(...entry.result);
        }
      } else {
        results = {};
        for (const [_idx, entry] of ordered) {
          results[entry.key!] = entry.result;
        }
      }
      const instance = await this.env.WORKFLOW.get(report.parentId);
      await instance.sendEvent({
        type: `${report.stateName}-complete-${report.parentId}`,
        payload: error ? { error } : { results },
      });
    }

    return Response.json({ ok: true });
  }
}"""

    def _emit_dispatcher_container(self) -> str:
        """Emit the container class used by the dispatcher Durable Object namespace."""
        return """\
export class DispatcherContainer extends Container {
  defaultPort = 8080;
  sleepAfter = "5s";

}
// Route container outbound requests through the workflow Worker bindings.
// This is the same Container-to-binding path used by regular SeBS containers;
// the workflow Worker does not expose public storage proxy routes.
DispatcherContainer.outboundByHost = {
  "sebs.r2": (request, env, ctx) => handleR2Request(request, env, ctx),
  "sebs.kv": (request, env, ctx) => handleNoSQLRequest(request, env, ctx),
};"""

    def _map_func_name(self, state: Map) -> str:
        """Return the task function name used by a Map state."""
        if isinstance(state.funcs, dict):
            first_state = next(iter(state.funcs.values()))
            return first_state["func_name"]
        return state.funcs[0]

    def _map_item_input_expr(self, state: Map, root: str) -> str:
        """Return the JavaScript expression used as each Map dispatch input."""
        if state.common_params:
            param_spread = ", ".join(
                f"{json.dumps(p)}: {self._js_var_path(root, p)}" for p in state.common_params
            )
            return f"({{ array_element: item, {param_spread} }})"
        return "item"

    @staticmethod
    def _js_var_path(root: str, dotted_path: str) -> str:
        """Convert a dotted path like 'astros.people' to JS access 'root.astros.people'."""
        parts = dotted_path.split(".")
        return root + "." + ".".join(parts)

    @staticmethod
    def _js_identifier(name: str) -> str:
        """Convert an FSM state name into a JavaScript-safe identifier fragment."""
        identifier = re.sub(r"\W", "_", name)
        if identifier and identifier[0].isdigit():
            identifier = f"_{identifier}"
        return identifier or "state"

    def encode_task(self, state: Task) -> Union[dict, List[dict]]:
        """Not used — generation bypasses the standard encode pipeline."""
        raise NotImplementedError("Use generate() directly")

    def encode_switch(self, state: Switch) -> Union[dict, List[dict]]:
        """Not used — generation bypasses the standard encode pipeline."""
        raise NotImplementedError("Use generate() directly")

    def encode_map(self, state: Map) -> Union[dict, List[dict]]:
        """Not used — generation bypasses the standard encode pipeline."""
        raise NotImplementedError("Use generate() directly")

    def encode_parallel(self, state: Parallel) -> Union[dict, List[dict]]:
        """Not used — generation bypasses the standard encode pipeline."""
        raise NotImplementedError("Use generate() directly")

    def encode_loop(self, state: Loop) -> Union[dict, List[dict]]:
        """Not used — generation bypasses the standard encode pipeline."""
        raise NotImplementedError("Use generate() directly")
