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

## Example workflows

Drag any file from [`examples/`](examples/) onto the ComfyUI canvas.
Each carries a READ ME note explaining exactly what to click. All three
were generated and load-verified by the ComfyUI frontend itself; the
first was also executed end-to-end in CI conditions.

- **`repeat-loop-demo.json`** — runs out of the box, zero models/keys:
  a 3-pass counted loop you can watch work (final preview shows `xxxx`),
  plus a Lazy Switch branch demo. Start here.
- **`quality-mode-switch.json`** — full draft/final txt2img graph: pick
  a checkpoint + a lightning/turbo LoRA and the `mode` toggle switches
  model path, steps, and cfg in one click.
- **`minimax-h3-shot-chain.json`** — the long-animation recipe: N
  MiniMax H3 shots chained first-frame ← last-frame, frames accumulated
  across passes, assembled into one video. Needs a Comfy API key and
  credits.

The nodes log every decision to the ComfyUI terminal (`[Repeat Open]
pass 2 of 3 ...`, `[Quality Mode Switch] DRAFT mode: ...`), and every
error names the exact input to fix.

## Install

```sh
cd ComfyUI/custom_nodes
git clone https://github.com/JimothyJohn/comfy-toolset
```

Restart ComfyUI. No pip installs needed.

## Development

```sh
./Quickstart        # install dev env, lint, format, unit tests
./Quickstart -u     # unit tests only
./Quickstart -i     # live tests against a real ComfyUI (needs COMFYUI_DIR)
```

Stack: `uv`, `ruff`, `ty`, `pytest`. Unit tests run without ComfyUI
installed.

## Staying compatible with ComfyUI

Beyond the structural defenses (zero runtime deps; no ComfyUI imports
except the guarded, documented `comfy_execution` expansion API), the
repo tests against the real thing:

- **Integration suite** (`tests/integration/`): boots an actual
  ComfyUI server (`--cpu`, no models) with this pack symlinked into
  `custom_nodes` and drives it over the public HTTP API — node
  registration (`/object_info`), lazy-evaluation flags, and workflow
  execution (`/prompt` + `/history`) including full loop expansion,
  plus a direct canary on the `comfy_execution.graph_utils` surface.
- **Every PR** runs the suite against the **latest ComfyUI release**
  (`comfy-integration` job in `ci.yml`).
- **Daily** (`compat.yml`), the same suite runs against ComfyUI
  **master** and the latest release; a failure opens or updates a
  `comfy-compat` issue, so upstream drift is caught the day it lands.

Provision a throwaway checkout for local runs:

```sh
./scripts/setup-comfyui.sh /tmp/ComfyUI master   # or latest-release, or a tag
COMFYUI_DIR=/tmp/ComfyUI ./Quickstart -i
```
