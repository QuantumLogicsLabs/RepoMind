---
name: Agent Quality Issue
about: The agent planned poorly, used the wrong tool, produced bad code, or wrote a poor PR description
title: "[AGENT] "
labels: agent-quality
assignees: ""
---

## Issue Type

- [ ] **Bad plan** — Planner decomposed the instruction into wrong or unnecessary steps
- [ ] **Wrong tool selected** — Executor chose the wrong tool for a step
- [ ] **Bad code generated** — Generated code is incorrect, broken, or doesn't match the instruction
- [ ] **Poor diff / PR description** — Output from `diff_generator` or `pr_tool` is unclear or wrong
- [ ] **Memory / context loss** — Agent forgot earlier context during a refinement (`POST /refine`)
- [ ] **Infinite / runaway plan** — Agent produced more steps than `MAX_PLAN_STEPS` or looped
- [ ] Other: <!-- describe -->

## Instruction Given

```
# Paste the exact instruction sent to POST /run or POST /refine
```

## Target Repository

<!-- URL or description of the repo (can be anonymised). Language, size, structure. -->

## What the Agent Did

```json
// Paste the plan steps and/or tool decisions if available
```

## What It Should Have Done

<!-- Describe the correct behaviour: expected plan steps, correct tool, expected code output. -->

## LLM / Model

<!-- e.g. gpt-4o, claude-3-5-sonnet-20241022, gpt-3.5-turbo -->

## Relevant Prompt Templates

<!-- Which prompt was likely involved? -->

- [ ] `prompts/system_prompt.py`
- [ ] `prompts/code_gen_prompt.py`
- [ ] `prompts/pr_description.py`
- [ ] Unknown / unsure

## Additional Context

<!-- Logs, job ID, session ID, or any other useful info. -->
