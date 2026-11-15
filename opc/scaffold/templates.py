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
