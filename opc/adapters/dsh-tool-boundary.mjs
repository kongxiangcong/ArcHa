// Loaded by DSH through an absolute --patch module entry. Model transport stays
// in the trusted host; every tool effect goes through the confined bash runner.
// Guard contract: deepseek-ai/deepseek-harness@ce7073d51254c26cd63b22a60835b8f948deb447,
// packages/core/tools/src/index.ts (tools.guard); patches load this absolute module.
export const name = 'archa-tool-boundary';
export const inject = ['tools'];
export function apply(ctx) {
  if (typeof ctx.tools.guard !== 'function') {
    throw new Error('ArcHa requires the DSH monotonic tool guard capability');
  }
  ctx.tools.guard(exec => {
    const args = exec.arguments || {};
    return exec.name === 'bash' && args.sandbox_permissions === undefined && !args.run_in_background
      ? undefined
      : 'ArcHa task boundary: use foreground confined bash without permission escalation for all file access and execution';
  });
}
