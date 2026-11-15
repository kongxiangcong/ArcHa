"""Domain-neutral topic templates."""
GOAL = '# Goal\n\n## Objective\n{goal}\n\n## Scope\n\n## Environment entry\n\n## Completion criteria\n'
STATE = '''# Exploration State
STATUS: IN_PROGRESS
MAX_ROUNDS: {max_rounds}

## 1. Confirmed facts and scope

## 2. Mechanism model and explanations

## 3. Closed branches and conditions

## 4. Open questions and blockers

## 5. Latest cognitive update
'''

PIM_GOAL = GOAL + '''
## PIM investigation context (optional)
<!-- Record simulator/source entry, workload and mapping, hardware assumptions,
measurement command and correctness checks when relevant to this objective.
Check the critical path or benefit bound before choosing a costly experiment.
Verify that each proposed intervention actually changes the intended mechanism. -->
'''


def goal_template(name):
    if name not in {'default', 'pim'}:
        raise ValueError('unknown topic template: ' + name)
    return PIM_GOAL if name == 'pim' else GOAL
