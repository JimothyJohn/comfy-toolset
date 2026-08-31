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

### Repeat Open / Repeat Close (`toolset`)

Counted loop for running a subgraph N times, feeding each pass's
outputs back in as the next pass's inputs — e.g. chaining multiple
MiniMax (Hailuo) shots into one long animation by carrying the last
frame of shot *k* in as the first frame of shot *k+1*.

ComfyUI graphs are DAGs, so the loop works via [node
expansion](https://docs.comfy.org/custom-nodes/backend/expansion):
after each pass, Repeat Close clones the subgraph between the pair and
splices it into the execution graph, until `iterations` passes have
run. Only two wires are required — `flow_control` from Open to Close,
plus whichever of the four any-type value slots you use. The
`iterations` count must stay a widget value (not a connection); it is
read before the graph runs. Leave the `_remaining` input unconnected —
it's the loop's internal counter.

Repeat Open also outputs `index` (0-based pass number) and
`iterations`, for driving per-shot prompts, seeds, or filenames.

Shot-chaining sketch:

```
start frame ── value0 → Repeat Open ── value0 (current first frame) → MiniMax H3 shot
                 │            │ index → per-shot prompt/seed select        │
                 │            └ value1 (frames so far) ─→ Image Batch ←────┤ (shot frames)
                 │                                            │            │ (last frame)
                 └ flow_control → Repeat Close ← value1 ──────┘            │
                                       ↑ value0 ←──────────────────────────┘
                                       └ value1 out → all frames → video combine
```

Each pass: `value0` carries the latest last-frame into the next shot,
`value1` accumulates the growing frame batch, and after N passes Repeat
Close's `value1` holds every frame of the full animation.

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
