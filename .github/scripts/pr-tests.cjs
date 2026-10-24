// This controller is loaded only from the trusted workflow commit, never a PR.
const SUITES = new Set(['cloud', 'openwhisk', 'local']);
const WRITE_PERMISSIONS = new Set(['admin', 'maintain', 'write']);

function parseCommand(body) {
  const match = /^\/test (cloud|openwhisk|local) ([0-9a-f]{40})$/.exec(body.trim());
  if (!match) {
    throw new Error('Usage: /test <cloud|openwhisk|local> <full lowercase PR head SHA>');
  }
  return { suite: match[1], sha: match[2] };
}

async function validatePR(github, context, { pr, suite, sha }) {
  if (!/^[1-9][0-9]*$/.test(pr) || !Number.isSafeInteger(Number(pr)) ||
      !SUITES.has(suite) || !/^[0-9a-f]{40}$/.test(sha)) {
    throw new Error('Invalid PR number, test suite, or full commit SHA');
  }
  const { data } = await github.rest.pulls.get({
    ...context.repo, pull_number: Number(pr),
  });
  const repository = `${context.repo.owner}/${context.repo.repo}`;
  if (data.state !== 'open' || data.base.ref !== 'master' ||
      data.base.repo.full_name !== repository) {
    throw new Error('Expected an open PR targeting this repository\'s master branch');
  }
  if (data.head.sha !== sha) {
    throw new Error('The PR head changed; review the current commit and post a new command');
  }
  return { pr, suite, sha };
}

async function request({ github, context, core }) {
  const { issue, comment } = context.payload;
  if (!issue?.pull_request || comment?.user.type !== 'User' ||
      !comment.body.startsWith('/test ')) {
    return;
  }
  // Query current repository permissions, not author_association or PR ownership.
  const { data } = await github.rest.repos.getCollaboratorPermissionLevel({
    ...context.repo, username: comment.user.login,
  });
  if (!WRITE_PERMISSIONS.has(data.permission)) {
    core.notice('Ignoring test request: commenter does not have repository write access');
    return;
  }
  const { suite, sha } = parseCommand(comment.body);
  const pr = String(issue.number);
  await validatePR(github, context, { pr, suite, sha });
  await github.rest.actions.createWorkflowDispatch({
    ...context.repo,
    workflow_id: 'pr-tests.yml',
    ref: 'master',
    inputs: { pr, suite, reviewed_sha: sha },
  });
  await core.summary.addRaw(`Requested ${suite} for PR #${pr} at ${sha}`).write();
}

function runURL(context) {
  return `${context.serverUrl}/${context.repo.owner}/${context.repo.repo}/actions/runs/${context.runId}`;
}

async function status(github, context, { sha, suite, state, description }) {
  await github.rest.repos.createCommitStatus({
    ...context.repo, sha, state, description,
    context: `regression/${suite}`,
    target_url: runURL(context),
  });
}

async function resolve({ github, context, core, env = process.env }) {
  if (context.eventName !== 'workflow_dispatch' || context.ref !== 'refs/heads/master') {
    throw new Error('PR tests must be dispatched on master');
  }
  const target = await validatePR(github, context, {
    pr: env.TEST_PR, suite: env.TEST_SUITE, sha: env.TEST_SHA,
  });
  // Publish pending before emitting outputs that allow regression jobs to start.
  await status(github, context, {
    ...target, state: 'pending', description: 'Approved regression run is starting',
  });
  core.setOutput('sha', target.sha);
  core.setOutput('suite', target.suite);
  await core.summary.addRaw(`Testing PR #${target.pr} at ${target.sha}`).write();
}

async function report({ github, context, env = process.env }) {
  if (!SUITES.has(env.TEST_SUITE) || !/^[0-9a-f]{40}$/.test(env.TEST_SHA)) {
    throw new Error('Invalid regression status target');
  }
  const result = {
    cloud: env.CLOUD_RESULT,
    openwhisk: env.OPENWHISK_RESULT,
    local: env.LOCAL_RESULT,
  }[env.TEST_SUITE];
  const state = result === 'success' ? 'success' : result === 'failure' ? 'failure' : 'error';
  await status(github, context, {
    sha: env.TEST_SHA, suite: env.TEST_SUITE, state,
    description: `Approved regression run: ${result}`,
  });
}

module.exports = { parseCommand, validatePR, request, resolve, report };
