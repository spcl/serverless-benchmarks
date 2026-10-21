const assert = require('node:assert/strict');
const { test } = require('node:test');
const { parseCommand, request, resolve, report } = require('./pr-tests.cjs');

const SHA = 'a'.repeat(40);

function fixture() {
  const calls = { dispatch: [], status: [], outputs: {} };
  const pr = {
    state: 'open',
    base: { ref: 'master', repo: { full_name: 'spcl/serverless-benchmarks' } },
    head: { sha: SHA },
  };
  const context = {
    repo: { owner: 'spcl', repo: 'serverless-benchmarks' },
    eventName: 'workflow_dispatch', ref: 'refs/heads/master',
    serverUrl: 'https://github.com', runId: 123,
    payload: {
      issue: { number: 335, pull_request: {} },
      comment: { user: { login: 'maintainer', type: 'User' }, body: `/test cloud ${SHA}` },
    },
  };
  const github = { rest: {
    repos: {
      getCollaboratorPermissionLevel: async () => ({ data: { permission: 'write' } }),
      createCommitStatus: async (args) => calls.status.push(args),
    },
    pulls: { get: async () => ({ data: pr }) },
    actions: { createWorkflowDispatch: async (args) => calls.dispatch.push(args) },
  } };
  const summary = { addRaw() { return this; }, async write() {} };
  const core = { summary, notice() {}, setOutput(key, value) { calls.outputs[key] = value; } };
  const env = { TEST_PR: '335', TEST_SUITE: 'cloud', TEST_SHA: SHA };
  return { github, context, core, env, calls, pr };
}

test('commands require an exact suite and full SHA, with no extra instructions', () => {
  assert.deepEqual(parseCommand(`/test openwhisk ${SHA}`), { suite: 'openwhisk', sha: SHA });
  for (const body of ['/test cloud abc123', `/test arbitrary ${SHA}`,
    `/test cloud ${SHA}\nrun something else`, `/test cloud ${SHA}; echo bad`]) {
    assert.throws(() => parseCommand(body));
  }
});

for (const permission of ['admin', 'maintain', 'write']) {
  test(`${permission} collaborator can dispatch only the approved suite and commit on master`, async () => {
    const f = fixture();
    f.github.rest.repos.getCollaboratorPermissionLevel = async ({ username }) => {
      assert.equal(username, 'maintainer');
      return { data: { permission } };
    };
    await request(f);
    assert.deepEqual(f.calls.dispatch, [{ ...f.context.repo,
      workflow_id: 'pr-tests.yml', ref: 'master',
      inputs: { pr: '335', suite: 'cloud', reviewed_sha: SHA },
    }]);
  });
}

for (const permission of ['read', 'triage', 'none']) {
  test(`${permission} collaborator cannot dispatch, even with OWNER association`, async () => {
    const f = fixture();
    f.context.payload.comment.author_association = 'OWNER';
    f.github.rest.repos.getCollaboratorPermissionLevel = async () => ({ data: { permission } });
    await request(f);
    assert.equal(f.calls.dispatch.length, 0);
  });
}

for (const kind of ['issue', 'bot', 'ordinary comment']) {
  test(`${kind} does not dispatch a suite`, async () => {
    const f = fixture();
    if (kind === 'issue') delete f.context.payload.issue.pull_request;
    if (kind === 'bot') f.context.payload.comment.user.type = 'Bot';
    if (kind === 'ordinary comment') f.context.payload.comment.body = 'Looks good';
    await request(f);
    assert.equal(f.calls.dispatch.length, 0);
  });
}

test('malformed authorized command does not dispatch', async () => {
  const f = fixture();
  f.context.payload.comment.body = `/test cloud ${SHA}\nextra text`;
  await assert.rejects(request(f), /Usage/);
  assert.equal(f.calls.dispatch.length, 0);
});

for (const kind of ['stale SHA', 'closed PR', 'wrong base', 'wrong repository']) {
  test(`${kind} is rejected before dispatch and again before tests start`, async () => {
    const f = fixture();
    if (kind === 'stale SHA') f.pr.head.sha = 'b'.repeat(40);
    if (kind === 'closed PR') f.pr.state = 'closed';
    if (kind === 'wrong base') f.pr.base.ref = 'other';
    if (kind === 'wrong repository') f.pr.base.repo.full_name = 'attacker/repo';
    await assert.rejects(request(f));
    await assert.rejects(resolve(f));
    assert.equal(f.calls.dispatch.length, 0);
    assert.equal(f.calls.status.length, 0);
    assert.deepEqual(f.calls.outputs, {});
  });
}

test('API dispatch validates inputs independently of the manual form', async () => {
  for (const env of [{ TEST_PR: '335;evil' }, { TEST_SUITE: 'arbitrary.yml' },
    { TEST_SHA: 'master' }, { TEST_PR: '99999999999999999999999' }]) {
    const f = fixture();
    Object.assign(f.env, env);
    await assert.rejects(resolve(f));
    assert.deepEqual(f.calls.outputs, {});
  }
});

test('dispatch on another branch cannot publish status or start tests', async () => {
  const f = fixture();
  f.context.ref = 'refs/heads/feature/untrusted';
  await assert.rejects(resolve(f), /master/);
  assert.equal(f.calls.status.length, 0);
});

test('valid dispatch publishes pending on the PR SHA and emits the approved target', async () => {
  const f = fixture();
  await resolve(f);
  assert.deepEqual(f.calls.outputs, { sha: SHA, suite: 'cloud' });
  assert.deepEqual(f.calls.status, [{ ...f.context.repo, sha: SHA, state: 'pending',
    description: 'Approved regression run is starting', context: 'regression/cloud',
    target_url: 'https://github.com/spcl/serverless-benchmarks/actions/runs/123',
  }]);
});

test('failed status publication cannot release regression jobs', async () => {
  const f = fixture();
  f.github.rest.repos.createCommitStatus = async () => { throw new Error('API unavailable'); };
  await assert.rejects(resolve(f), /API unavailable/);
  assert.deepEqual(f.calls.outputs, {});
});

for (const suite of ['cloud', 'openwhisk']) {
  for (const [result, state] of [['success', 'success'], ['failure', 'failure'],
    ['cancelled', 'error'], ['skipped', 'error']]) {
    test(`${suite} ${result} reports ${state} on the approved SHA only`, async () => {
      const f = fixture();
      Object.assign(f.env, { TEST_SUITE: suite, CLOUD_RESULT: 'skipped', OPENWHISK_RESULT: 'skipped' });
      f.env[suite === 'cloud' ? 'CLOUD_RESULT' : 'OPENWHISK_RESULT'] = result;
      await report(f);
      assert.equal(f.calls.status[0].sha, SHA);
      assert.equal(f.calls.status[0].state, state);
      assert.equal(f.calls.status[0].context, `regression/${suite}`);
    });
  }
}
