# comfy-toolset

Minimal ComfyUI switch nodes for flipping a workflow between a **draft**
profile (LoRA-accelerated, few steps, short clip) and a **final** profile
(base model, full steps, maximum length, no LoRA) with a single toggle.

Zero runtime dependencies. The nodes never import ComfyUI internals — the
only API surface is the node-definition contract, so the pack stays
compatible across ComfyUI upgrades.

## Nodes

### Quality Mode Switch (`toolset`)

One boolean (`draft` / `final`) that routes a MODEL and reconfigures the
numbers around it:

| input | draft default | final default |
|---|---|---|
| model | `draft_model` (lazy) | `final_model` (lazy) |
| fps | 16.0 | 24.0 |
| frames | 33 | 121 |
| steps | 4 | 30 |
| cfg | 1.0 | 3.5 |

Outputs: `model`, `fps` (FLOAT), `frames` (INT), `steps` (INT), `cfg`
(FLOAT), `is_final` (BOOLEAN).

Both model inputs are **lazy**: only the selected branch is evaluated, so
in final mode the LoRA loader chain upstream of `draft_model` is truly
bypassed — never loaded, never executed. Wiring:

```
CheckpointLoader ──┬── LoraLoader ── draft_model ─┐
                   └───────────────── final_model ─┤ Quality Mode Switch ── model → KSampler
                                                   │   fps    → video combine
                                                   │   frames → empty latent / length
                                                   │   steps  → KSampler
                                                   │   cfg    → KSampler
                                                   └── is_final → other LazySwitch nodes
```

### Lazy Switch (Any) (`toolset`)

Generic two-way switch for any socket type (latents, images,
conditioning, …) with the same lazy bypass. Chain its `pick_b` from
`is_final` to hang more per-mode differences (an upscaler, an
interpolator) off the same toggle.

## Install

```sh
cd ComfyUI/custom_nodes
git clone https://github.com/JimothyJohn/comfy-toolset
```

Restart ComfyUI. No pip installs needed.

## Development

```sh
./Quickstart        # install dev env, lint, format, unit tests
./Quickstart -u     # tests only
```

Stack: `uv`, `ruff`, `pytest`. Tests run without ComfyUI installed.
