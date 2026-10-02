# Optexity Take-Home — Action Memory Cache

## What I implemented

This submission adds an action-memory layer around Browser Use so a successful agentic run can be cached and converted into deterministic Optexity actions.

Flow:

```text
Agentic task
→ Browser Use executes actions
→ JSONL action cache
→ deterministic Optexity automation
→ faster replay with no Browser Use page reasoning
```

The implementation spans both repositories required by the assignment:

- **browser-use**: records executed Browser Use actions.
- **optexity**: compiles the cache into deterministic automation, adds LLM-based generation, and adds an iterative optimization loop.

---

## Key files

### browser-use

```text
browser_use/agent/action_cache.py
browser_use/agent/service.py
tests/ci/infrastructure/test_action_cache.py
```

### optexity

```text
optexity/action_memory/compiler.py
optexity/action_memory/llm_compiler.py
optexity/action_memory/loop_optimizer.py

scripts/compile_action_cache.py
scripts/compile_action_cache_llm.py
scripts/optimize_action_memory_loop.py

test_automation.json
test_automation_cached.json
test_automation_saucedemo.json
test_automation_saucedemo_cached.json

tests/test_compile_action_cache.py
tests/test_llm_action_cache.py
tests/test_loop_optimizer.py
```

---

## Quick verification

### Optexity

```bash
python -m pytest tests -v
```

Expected result:

```text
26 passed
```

### Browser Use

```bash
python -m pytest tests/ci/infrastructure/test_action_cache.py -v
```

Expected result:

```text
3 passed
```

---

## Required implementation

### 1. Cache Browser Use actions

Enable the recorder with:

```bash
export BROWSER_USE_ACTION_CACHE_PATH=/path/to/action_cache.jsonl
```

Each executed action is appended as JSONL with:

- agent id
- step
- URL before action
- executed action
- resolved element metadata
- result

The recorder is fail-open so cache logging does not break the task.

### 2. Compile cache into deterministic Optexity actions

```bash
python scripts/compile_action_cache.py \
  --cache /path/to/action_cache.jsonl \
  --output /path/to/generated.json
```

The compiler:

- selects one Browser Use run;
- requires successful completion;
- skips failed and final `done` actions;
- supports cached input/click actions;
- prefers stable selectors;
- validates output using `Automation.model_validate()`.

Selector priority:

```text
data-test → id → name → aria-label → placeholder → XPath
```

### 3. Required RoboForm workflow

```text
https://www.roboform.com/filling-test-all-fields
```

Task:

```text
fill the full name as myname, address line one as xyz and line 2 as abc, city as SF
```

Files:

```text
test_automation.json
test_automation_cached.json
```

### 4. Extra multi-page workflow

SauceDemo was used to prove the approach also works across page transitions:

```text
login
→ add backpack to cart
→ open cart
→ checkout
→ fill customer information
→ continue to checkout overview
```

Files:

```text
test_automation_saucedemo.json
test_automation_saucedemo_cached.json
```

---

## Bonus 1 — automatic LLM generation

Implemented in:

```text
optexity/action_memory/llm_compiler.py
scripts/compile_action_cache_llm.py
```

Flow:

```text
cache + original task + relevant Optexity docs
→ structured-output LLM
→ Pydantic CacheSelection
→ deterministic compiler
→ Automation.model_validate()
```

The LLM selects which cached records are necessary. It does **not** invent selectors.

Example:

```bash
python scripts/compile_action_cache_llm.py \
  --cache /path/to/action_cache.jsonl \
  --output /path/to/generated.json \
  --task "fill the full name as myname, address line one as xyz and line 2 as abc, city as SF"
```

Validated results:

```text
RoboForm:
  selected records: [1, 2, 3, 4]
  generated nodes: 4
  deterministic replay: success
  Browser Use cache during replay: 0

SauceDemo:
  selected records: [1..10]
  generated nodes: 10
  deterministic replay: success
  Browser Use cache during replay: 0
```

---

## Bonus 2 — iterative optimization loop

Implemented in:

```text
optexity/action_memory/loop_optimizer.py
scripts/optimize_action_memory_loop.py
```

Flow:

```text
agentic seed
→ run and cache
→ compile deterministic nodes
→ rerun deterministic prefix + agentic fallback
→ recache residual work
→ merge/deduplicate
→ stop on convergence
→ final deterministic-only verification
```

The loop stops when:

- Browser Use has no useful residual actions;
- no new deterministic nodes are learned; or
- max iterations is reached.

The local task-allocation endpoint is configurable through the CLI instead of being hardcoded. This keeps the optimizer reusable across different local Optexity setups.

Example:

```bash
python scripts/optimize_action_memory_loop.py   --seed test_automation.json   --current-automation /path/to/current.json   --cache /path/to/cache.jsonl   --generated-dir /path/to/iterations   --task "fill the full name as myname, address line one as xyz and line 2 as abc, city as SF"   --endpoint-name <existing-optexity-endpoint>   --input-parameters-json '{}'
```

If the selected allocation endpoint requires input parameters, provide them as a JSON object:

```bash
--input-parameters-json '{"example_key":["example_value"]}'
```

### SauceDemo convergence result

```text
Iteration 1:
  Browser Use cache records: 11
  deterministic nodes learned: 10

Iteration 2:
  Browser Use cache records: 1
  useful residual actions: 0
  converged

Final verification:
  deterministic nodes: 10
  Browser Use cache records added: 0
  task completed successfully
```

This demonstrates convergence from an agentic workflow to a deterministic replay with no remaining Browser Use actions.

---

## Performance

Required RoboForm workflow, 3 runs each.

### Whole-task latency

```text
Agentic mean:              44.226s
Cached deterministic mean: 21.139s

Reduction: 52.2%
Speedup:   2.09x
```

### Action execution span

```text
Agentic mean:              26.914s
Cached deterministic mean:  4.016s

Reduction: 85.1%
Speedup:   6.70x
```

### Browser Use model tokens

Baseline RoboForm runs:

```text
18,110
18,094
18,311
```

Mean:

```text
~18,172 Browser Use model tokens/run
```

Deterministic cached replay uses command-based Optexity actions, so replayed actions require **zero Browser Use page-reasoning calls/tokens**.

---

## Tests

### Optexity

```bash
python -m pytest tests -v
```

Result:

```text
26 passed
```

### Browser Use recorder

```bash
python -m pytest tests/ci/infrastructure/test_action_cache.py -v
```

Result:

```text
3 passed
```

---

## Local execution

Action cache:

```bash
export BROWSER_USE_ACTION_CACHE_PATH=/path/to/cache.jsonl
```

Bonus 2 local automation override:

```bash
export OPTEXITY_TEST_AUTOMATION_PATH=/path/to/current.json
```

Run inference:

```bash
optexity inference --port 9000 --child_process_id 0
```

Then run the optimizer with an existing local Optexity endpoint used only to allocate the task:

```bash
python scripts/optimize_action_memory_loop.py   --seed test_automation.json   --current-automation /path/to/current.json   --cache /path/to/cache.jsonl   --generated-dir /path/to/iterations   --task "fill the full name as myname, address line one as xyz and line 2 as abc, city as SF"   --endpoint-name <existing-optexity-endpoint>   --input-parameters-json '{}'
```

If that endpoint requires inputs, pass them through `--input-parameters-json`.

---

## Summary

```text
Browser Use agent
→ cache executed actions
→ deterministic replay
→ lower latency and Browser Use token usage
→ LLM + docs + Pydantic automatic generation
→ iterative recaching and convergence
→ final deterministic-only replay
```

The required RoboForm workflow, multi-page SauceDemo workflow, Bonus 1, Bonus 2, and tests were all validated locally.
