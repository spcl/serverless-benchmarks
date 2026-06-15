"""Cloudflare Workflows code generator.

Translates SeBS FSM definitions (definition.json) into TypeScript source code
for a Cloudflare WorkflowEntrypoint class. The generated code uses a while/switch
state machine pattern where each FSM state maps to a switch case with step.do() calls.
"""

from typing import Dict, List, Set, Union

from sebs.faas.fsm import Generator, State, Task, Switch, Map, Parallel, Repeat, Loop


class CloudflareWorkflowGenerator(Generator):
    """Generate TypeScript Workflow code from FSM definitions."""

    def __init__(
        self,
        dispatcher_binding: str = "DISPATCHER",
        dispatcher_url: str = "",
    ):
        """Initialize the Cloudflare Workflow generator.

        Args:
            dispatcher_binding: Service binding name (used when dispatcher_url is empty).
            dispatcher_url: Direct HTTP URL for the dispatcher (container workers can't be
                called via service bindings from inside Workflow steps — use URL instead).
        """
        super().__init__()
        self._dispatcher_binding = dispatcher_binding
        self._dispatcher_url = dispatcher_url

    def generate(self) -> str:
        """Generate the complete TypeScript workflow source file."""
        cases = []
        for state in self.states.values():
            case_code = self._encode_state_case(state)
            cases.append(case_code)

        cases.append('      case "__end__":\n        return state;')

        switch_body = "\n".join(cases)

        if self._dispatcher_url:
            env_iface = "  WORKFLOW: any;"
        else:
            env_iface = f"  WORKFLOW: any;\n  {self._dispatcher_binding}: Fetcher;"

        return f"""\
import {{ WorkflowEntrypoint, WorkflowEvent, WorkflowStep }} from "cloudflare:workers";

interface Env {{
{env_iface}
}}

// Retry fetch on 502/503 or non-JSON responses (container cold-start / Durable Object reset).
// Any other non-2xx response is treated as a hard error and thrown immediately.
async function dispatchWithRetry(url: string, body: any, maxAttempts = 10): Promise<any> {{
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {{
    const r = await fetch(url, {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify(body),
    }});
    if (r.status === 503 || r.status === 502) {{
      const wait = Math.min(5000 * attempt, 30000);
      await new Promise((res) => setTimeout(res, wait));
      continue;
    }}
    const text = await r.text();
    if (!r.ok) {{
      throw new Error(`Dispatcher returned HTTP ${{r.status}}: ${{text.slice(0, 200)}}`);
    }}
    try {{
      return JSON.parse(text);
    }} catch (_) {{
      // Non-JSON response from container (e.g. proxy error during startup); retry.
      if (attempt < maxAttempts) {{
        const wait = Math.min(5000 * attempt, 30000);
        await new Promise((res) => setTimeout(res, wait));
        continue;
      }}
      throw new Error(`Dispatcher returned non-JSON after ${{maxAttempts}} attempts: ${{text.slice(0, 200)}}`);
    }}
  }}
  throw new Error(`Dispatcher unavailable after ${{maxAttempts}} attempts`);
}}

export class BenchmarkWorkflow extends WorkflowEntrypoint<Env, any> {{
  async run(event: WorkflowEvent<any>, step: WorkflowStep) {{
    let state = structuredClone(event.payload);
    let current = "{self.root.name}";

    while (true) {{
      switch (current) {{
{switch_body}
        default:
          throw new Error(`Unknown state: ${{current}}`);
      }}
    }}
  }}
}}

export default {{
  async fetch(request: Request, env: Env): Promise<Response> {{
    const url = new URL(request.url);
    if (request.method === "GET" && url.searchParams.has("id")) {{
      // Status poll: return current status without blocking.
      const id = url.searchParams.get("id")!;
      const instance = await env.WORKFLOW.get(id);
      const status = await instance.status();
      return Response.json({{
        status: status.status,
        output: (status as any).output ?? null,
        error: (status as any).error ?? null,
      }});
    }}
    // Create a new workflow instance and return its ID immediately.
    const payload = await request.json();
    const instance = await env.WORKFLOW.create({{ params: payload }});
    return Response.json({{ id: instance.id }}, {{ status: 202 }});
  }},
}};
"""

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
        fetch_setup, fetch_result = self._make_fetch_call(state.func_name)
        setup_line = f"\n            {fetch_setup}" if fetch_setup else ""
        var = state.name.replace("-", "_")

        is_terminal = next_state == '"__end__"'
        if is_terminal:
            merge_expr = f"{var}_result"
        else:
            merge_expr = (
                f'(typeof {var}_result === "object" && {var}_result !== null'
                f' && !Array.isArray({var}_result))'
                f"\n            ? {{...state, ...{var}_result}} : {var}_result"
            )

        if state.failure:
            return f"""\
      case "{state.name}": {{
        try {{
          const {var}_result = await step.do("{state.name}", async () => {{{setup_line}
            return {fetch_result};
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
        const {var}_result = await step.do("{state.name}", async () => {{{setup_line}
          return {fetch_result};
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
            val = case.val if isinstance(case.val, (int, float)) else f'"{case.val}"'
            conditions.append(f'        if ({var_path} {op} {val}) {{ current = "{case.next}"; }}')

        default = state.default if state.default else "__end__"
        else_clause = f'        else {{ current = "{default}"; }}'

        body = "\n".join(conditions)
        if len(conditions) > 1:
            lines = [conditions[0]]
            for c in conditions[1:]:
                lines.append("        else " + c.strip())
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
        """Encode a Map state as Promise.all with step.do() per item."""
        next_state = f'"{state.next}"' if state.next else '"__end__"'

        if isinstance(state.funcs, dict):
            first_state = next(iter(state.funcs.values()))
            func_name = first_state["func_name"]
        else:
            func_name = state.funcs[0]

        array_path = self._js_var_path("state", state.array)

        if state.common_params:
            param_spread = ", ".join(f"{p}: state.{p}" for p in state.common_params)
            input_expr = f"{{ array_element: item, {param_spread} }}"
        else:
            input_expr = "item"

        url = self._dispatcher_url if self._dispatcher_url else "http://dispatcher/"
        if self._dispatcher_url:
            map_body = (
                f'return await dispatchWithRetry("{url}", '
                f'{{ function: "{func_name}", input: {input_expr} }});'
            )
        else:
            fetcher = f"this.env.{self._dispatcher_binding}.fetch"
            map_body = (
                f'const r = await {fetcher}("{url}", {{\n'
                f"                method: \"POST\",\n"
                f'                headers: {{ "Content-Type": "application/json" }},\n'
                f'                body: JSON.stringify({{ function: "{func_name}", input: {input_expr} }}),\n'
                f"              }});\n"
                f"              return await r.json();"
            )
        return f"""\
      case "{state.name}": {{
        const items_{state.name.replace("-", "_")} = {array_path};
        const results_{state.name.replace("-", "_")} = await Promise.all(
          items_{state.name.replace("-", "_")}.map((item: any, i: number) =>
            step.do(`{state.name}_${{i}}`, async () => {{
              {map_body}
            }})
          )
        );
        {array_path} = results_{state.name.replace("-", "_")};
        current = {next_state};
        break;
      }}"""

    def _encode_parallel_case(self, state: Parallel) -> str:
        """Encode a Parallel state as Promise.all across branches."""
        next_state = f'"{state.next}"' if state.next else '"__end__"'

        branch_thunks = []
        result_merge_parts = []

        for i, branch in enumerate(state.branches):
            sub_states = {n: State.deserialize(n, s) for n, s in branch.states.items()}
            ordered = self._order_branch_states(branch.root, sub_states)

            if len(ordered) == 1 and isinstance(ordered[0], Task):
                task = ordered[0]
                fetch_setup, fetch_result = self._make_fetch_call(task.func_name)
                setup_line = f"\n          {fetch_setup}" if fetch_setup else ""
                thunk = (
                    f'        step.do("{branch.root}", async () => {{{setup_line}\n'
                    f"          return {fetch_result};\n"
                    f"        }})"
                )
            else:
                steps_code = self._encode_branch_steps(ordered)
                thunk = (
                    f"        (async () => {{\n"
                    f"          let branchState = JSON.parse(JSON.stringify(state));\n"
                    f"{steps_code}\n"
                    f"          return branchState;\n"
                    f"        }})()"
                )

            branch_thunks.append(thunk)
            result_merge_parts.append(
                f'        "{branch.root}": parallelResults_{state.name.replace("-", "_")}[{i}]'
            )

        thunks_joined = ",\n".join(branch_thunks)
        merge_joined = ",\n".join(result_merge_parts)

        return f"""\
      case "{state.name}": {{
        const parallelResults_{state.name.replace("-", "_")} = await Promise.all([
{thunks_joined},
        ]);
        state = {{
{merge_joined},
        }};
        current = {next_state};
        break;
      }}"""

    def _encode_repeat_case(self, state: Repeat) -> str:
        """Encode a Repeat state as a counted for loop."""
        next_state = f'"{state.next}"' if state.next else '"__end__"'
        fetch_setup, fetch_result = self._make_fetch_call(state.func_name)
        setup_line = f"\n            {fetch_setup}" if fetch_setup else ""

        return f"""\
      case "{state.name}": {{
        for (let i = 0; i < {state.count}; i++) {{
          state = await step.do(`{state.name}_${{i}}`, async () => {{{setup_line}
            return {fetch_result};
          }});
        }}
        current = {next_state};
        break;
      }}"""

    def _encode_loop_case(self, state: Loop) -> str:
        """Encode a Loop state as a sequential for loop over an array."""
        next_state = f'"{state.next}"' if state.next else '"__end__"'
        array_path = self._js_var_path("state", state.array)
        url = self._dispatcher_url if self._dispatcher_url else "http://dispatcher/"
        if self._dispatcher_url:
            # Container dispatcher: use retry wrapper
            fetch_call_template = (
                f'return await dispatchWithRetry("{url}", {{ function: "{state.func_name}", '
                f"input: {array_path}[i] }});"
            )
        else:
            fetcher = f"this.env.{self._dispatcher_binding}.fetch"
            fetch_call_template = (
                f'const r = await {fetcher}("{url}", {{\n'
                f'              method: "POST",\n'
                f'              headers: {{ "Content-Type": "application/json" }},\n'
                f'              body: JSON.stringify({{ function: "{state.func_name}", '
                f"input: {array_path}[i] }}),\n"
                f"            }});\n"
                f"            return await r.json();"
            )

        return f"""\
      case "{state.name}": {{
        for (let i = 0; i < {array_path}.length; i++) {{
          {array_path}[i] = await step.do(`{state.name}_${{i}}`, async () => {{
            {fetch_call_template}
          }});
        }}
        current = {next_state};
        break;
      }}"""

    def _encode_branch_steps(self, ordered_states: List[State]) -> str:
        """Encode a sequence of states within a parallel branch."""
        lines = []
        for s in ordered_states:
            if isinstance(s, Task):
                fetch_setup, fetch_result = self._make_fetch_call(s.func_name)
                setup_line = f"\n              {fetch_setup}" if fetch_setup else ""
                var = s.name.replace("-", "_")
                lines.append(
                    f'          const {var}_result = await step.do("{s.name}", async () => {{{setup_line}\n'
                    f"            return {fetch_result};\n"
                    f"          }});\n"
                    f"          branchState = (typeof {var}_result === \"object\" && {var}_result !== null && !Array.isArray({var}_result))\n"
                    f"            ? {{...branchState, ...{var}_result}} : {var}_result;"
                )
            elif isinstance(s, Map):
                if isinstance(s.funcs, dict):
                    first_state = next(iter(s.funcs.values()))
                    func_name = first_state["func_name"]
                else:
                    func_name = s.funcs[0]

                array_path = self._js_var_path("branchState", s.array)

                if s.common_params:
                    param_spread = ", ".join(f"{p}: branchState.{p}" for p in s.common_params)
                    input_expr = f"{{ array_element: item, {param_spread} }}"
                else:
                    input_expr = "item"

                url = self._dispatcher_url if self._dispatcher_url else "http://dispatcher/"
                if self._dispatcher_url:
                    branch_map_body = (
                        f'return await dispatchWithRetry("{url}", '
                        f'{{ function: "{func_name}", input: {input_expr} }});'
                    )
                else:
                    fetcher = f'this.env.{self._dispatcher_binding}.fetch'
                    branch_map_body = (
                        f'const r = await {fetcher}("{url}", {{\n'
                        f'                  method: "POST",\n'
                        f'                  headers: {{ "Content-Type": "application/json" }},\n'
                        f'                  body: JSON.stringify({{ function: "{func_name}",'
                        f" input: {input_expr} }}),\n"
                        f"                }});\n"
                        f"                return await r.json();"
                    )
                lines.append(
                    f"          {array_path} = await Promise.all(\n"
                    f"            {array_path}.map((item: any, i: number) =>\n"
                    f"              step.do(`{s.name}_${{i}}`, async () => {{\n"
                    f"                {branch_map_body}\n"
                    f"              }})\n"
                    f"            )\n"
                    f"          );"
                )
        return "\n".join(lines)

    def _order_branch_states(self, root: str, states: Dict[str, State]) -> List[State]:
        """Return branch states in execution order (BFS from root)."""
        ordered: List[State] = []
        visited: Set[str] = set()
        queue = [root]

        while queue:
            name = queue.pop(0)
            if name in visited or name not in states:
                continue
            visited.add(name)
            state = states[name]
            ordered.append(state)
            nxt = getattr(state, "next", None)
            if nxt:
                queue.append(nxt)

        return ordered

    def _make_fetch_call(self, func_name: str) -> tuple[str, str]:
        """Generate a fetch call to the dispatcher (service binding or direct URL).

        Returns a 2-tuple: (setup_statement, result_expression).
        setup_statement is JS code to run before the return, may be empty string.
        result_expression is the JS expression whose value is the parsed JSON result.
        """
        url = self._dispatcher_url if self._dispatcher_url else "http://dispatcher/"
        if self._dispatcher_url:
            # Container dispatcher: use retry wrapper to handle cold-start 503s.
            setup = ""
            result = (
                f'await dispatchWithRetry("{url}", '
                f'{{ function: "{func_name}", input: state }})'
            )
        else:
            fetcher = f"this.env.{self._dispatcher_binding}.fetch"
            setup = (
                f'const r = await {fetcher}("{url}", {{\n'
                f'            method: "POST",\n'
                f'            headers: {{ "Content-Type": "application/json" }},\n'
                f'            body: JSON.stringify({{ function: "{func_name}", input: state }}),\n'
                f"          }});"
            )
            result = "await r.json()"
        return setup, result

    @staticmethod
    def _js_var_path(root: str, dotted_path: str) -> str:
        """Convert a dotted path like 'astros.people' to JS access 'root.astros.people'."""
        parts = dotted_path.split(".")
        return root + "." + ".".join(parts)

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
