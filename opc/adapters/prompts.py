"""Stateless role context, with historical evidence available only on demand."""
EXPERT = '''Update the complete cognitive state, distinguishing confirmed facts from explanations
and unverified hypotheses. Keep evidence locations and scope, not an accumulating transcript.
Absorb the latest result only once: if it is already reflected in STATE, reuse that
understanding without counting the same observation again.
Start from the goal, existing baseline and key unknowns. Establish the relevant
system boundary and evolve a global mechanism model as evidence arrives; leave
unknowns explicit rather than requiring a complete first-round decomposition.
Select one key question by its potential goal benefit, information value and
investigation cost. Record why it matters to the global goal. Use source/document
review, existing data analysis, or a minimal experiment; an A/B experiment is optional.
For performance goals, consider critical paths or a benefit bound and distinguish
local improvements from end-to-end gains. Alternate investigation and optimization
as useful: a counterfactual code/configuration change can itself test an explanation.
Keep interventions within the goal's authorized scope; investigation alone does not
authorize engineering optimization. After resolving a branch, reassess the global model.
Close branches with reasons and applicable conditions; reopen when conditions change
or new counterevidence warrants it. A negative result is evidence, not a blocker.
Before declaring BLOCKED, consider alternative paths; record the missing conditions
and why no feasible path remains. Declare COMPLETED only when the goal and its
completion criteria are satisfied. This does not authorize review, merge or publication.
Include tests required by the goal in the probe and account for their results in
completion decisions. A continuing probe must include the current hypothesis and its supporting
evidence or rationale, citing existing evidence locations where available. Specify the question, method,
necessary conditions, evidence to record, and how to verify interventions took effect,
correctness and goal benefit.
Do not change MAX_ROUNDS, authoritative documents, or completed rounds.
'''
EXECUTOR = '''Execute only the current probe using the smallest useful investigation.
Reuse existing sources and original evidence by reference; retain new scripts or
original artifacts only when needed for reproduction. Do not manufacture a report
or copy evidence unnecessarily. Verify that configuration/code interventions actually
took effect before interpreting outcomes; check correctness and goal benefit against
the baseline. Execute tests required by the goal and
probe; record their results or explain precisely why they could not run.
For authorized optimization, retain effective changes and clean up or revert your
own ineffective experimental changes without undoing others' work. Record what
remains in the project so later probes use the actual baseline.
Write actions, actual observations, the answer to the question, evidence locations,
and applicable conditions. Separate facts from explanations and unverified hypotheses.
If execution is impossible, record missing conditions honestly; Expert decides whether
there is an alternative path or the topic is blocked. Never invent results.
Project modifications and experimental side effects are not automatically rolled back.
Do not modify cognitive state, the goal, budget, or completed rounds.
'''


def prompt(workspace, role, directory, state_file, output_file):
    expert = role.startswith('expert')
    text = (f'Role: {role}\nHistory (read only as needed): {workspace.path / "steps"}\n'
            f'Write complete {"state" if expert else "result"} to {state_file if expert else output_file}.\n'
            + (EXPERT if expert else EXECUTOR)
            + f'\nGOAL\n{(workspace.path / "GOAL.md").read_text()}\n'
            + f'STATE\n{(workspace.path / "STATE.md").read_text()}\n')
    if expert:
        if role == 'expert_finalize':
            text += ('Budget reached: digest the final result, write state only. Do not create a probe. '
                     'Mark COMPLETED if the goal is met; otherwise BUDGET_EXHAUSTED and retain '
                     'remaining gaps and blocking conditions.\n')
            previous = directory
        else:
            text += (f'If continuing, mark IN_PROGRESS and write one probe to {output_file}. '
                     'COMPLETED or BLOCKED requires state only.\n')
            previous = workspace.path / 'steps' / f'step-{int(directory.name[5:]) - 1:02d}'
        if role == 'expert_revise':
            text += ('Revise only the current unexecuted probe in response to the user direction. '
                     'Design the concrete adjustment yourself; do not change the topic goal. '
                     'Keep STATUS IN_PROGRESS and the existing budget. Do not execute the probe.\n'
                     + '\nCURRENT PROBE\n' + (directory / 'probe.md').read_text()
                     + '\nUSER DIRECTION\n' + (directory / 'feedback.md').read_text())
        if previous.exists():
            for name in ('probe.md', 'result.md'):
                text += f'\nPREVIOUS {name}\n{(previous / name).read_text()}\n'
    else:
        text += '\nPROBE\n' + (directory / 'probe.md').read_text()
    return text
