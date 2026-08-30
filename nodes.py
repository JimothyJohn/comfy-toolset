"""Comfy Toolset — minimal workflow-switching nodes for ComfyUI.

Zero runtime dependencies. Nothing in this module imports ComfyUI itself;
the only API surface is the node-definition contract (INPUT_TYPES,
RETURN_TYPES, check_lazy_status), which keeps these nodes importable and
testable anywhere and resilient to ComfyUI-internal refactors.

Bypass mechanism: inputs marked ``"lazy": True`` are only evaluated when
``check_lazy_status`` asks for them, so everything upstream of the
unselected branch (LoRA loaders included) is never executed at all.
"""


class AnyType(str):
    """Type string that never compares unequal, so it matches any socket."""

    def __ne__(self, other):
        return False

    __hash__ = str.__hash__


ANY = AnyType("*")


class QualityModeSwitch:
    """Flip a workflow between a draft profile and a final profile.

    Draft: LoRA-accelerated model, few steps, short clip, low fps.
    Final: base model, full steps, maximum length, no LoRA.

    Wire the LoRA-patched model into ``draft_model`` and the clean model
    into ``final_model``; only the selected branch executes. Feed the
    numeric outputs into your sampler / EmptyLatent / video-combine nodes
    so one toggle reconfigures the whole graph.
    """

    CATEGORY = "toolset"
    FUNCTION = "route"
    RETURN_TYPES = ("MODEL", "FLOAT", "INT", "INT", "FLOAT", "BOOLEAN")
    RETURN_NAMES = ("model", "fps", "frames", "steps", "cfg", "is_final")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mode": (
                    "BOOLEAN",
                    {"default": False, "label_on": "final", "label_off": "draft"},
                ),
                "draft_fps": (
                    "FLOAT",
                    {"default": 16.0, "min": 0.01, "max": 480.0, "step": 0.01},
                ),
                "draft_frames": ("INT", {"default": 33, "min": 1, "max": 16384}),
                "draft_steps": ("INT", {"default": 4, "min": 1, "max": 10000}),
                "draft_cfg": (
                    "FLOAT",
                    {"default": 1.0, "min": 0.0, "max": 100.0, "step": 0.01},
                ),
                "final_fps": (
                    "FLOAT",
                    {"default": 24.0, "min": 0.01, "max": 480.0, "step": 0.01},
                ),
                "final_frames": ("INT", {"default": 121, "min": 1, "max": 16384}),
                "final_steps": ("INT", {"default": 30, "min": 1, "max": 10000}),
                "final_cfg": (
                    "FLOAT",
                    {"default": 3.5, "min": 0.0, "max": 100.0, "step": 0.01},
                ),
            },
            "optional": {
                "draft_model": ("MODEL", {"lazy": True}),
                "final_model": ("MODEL", {"lazy": True}),
            },
        }

    def check_lazy_status(self, mode, draft_model=None, final_model=None, **kwargs):
        if mode:
            return [] if final_model is not None else ["final_model"]
        return [] if draft_model is not None else ["draft_model"]

    def route(
        self,
        mode,
        draft_fps,
        draft_frames,
        draft_steps,
        draft_cfg,
        final_fps,
        final_frames,
        final_steps,
        final_cfg,
        draft_model=None,
        final_model=None,
    ):
        model = final_model if mode else draft_model
        if model is None:
            which = "final_model" if mode else "draft_model"
            raise ValueError(
                f"QualityModeSwitch: mode is '{'final' if mode else 'draft'}' "
                f"but nothing is connected to '{which}'."
            )
        if mode:
            return (model, final_fps, final_frames, final_steps, final_cfg, True)
        return (model, draft_fps, draft_frames, draft_steps, draft_cfg, False)


class LazySwitch:
    """Route one of two inputs of any type; the unpicked branch never runs.

    Generic companion to QualityModeSwitch: use it to bypass an upscaler,
    interpolator, conditioning chain, or any other subgraph. Chain its
    ``pick_b`` from QualityModeSwitch's ``is_final`` output to keep the
    whole workflow on one toggle.
    """

    CATEGORY = "toolset"
    FUNCTION = "route"
    RETURN_TYPES = (ANY,)
    RETURN_NAMES = ("value",)

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "pick_b": (
                    "BOOLEAN",
                    {"default": False, "label_on": "B", "label_off": "A"},
                ),
            },
            "optional": {
                "a": (ANY, {"lazy": True}),
                "b": (ANY, {"lazy": True}),
            },
        }

    @classmethod
    def VALIDATE_INPUTS(cls, input_types):
        # Accepting `input_types` tells ComfyUI to skip backend type
        # validation for this node's links; the wildcard inputs accept
        # any socket type by design.
        return True

    def check_lazy_status(self, pick_b, a=None, b=None, **kwargs):
        if pick_b:
            return [] if b is not None else ["b"]
        return [] if a is not None else ["a"]

    def route(self, pick_b, a=None, b=None):
        value = b if pick_b else a
        if value is None:
            raise ValueError(
                f"LazySwitch: input '{'b' if pick_b else 'a'}' is selected "
                "but not connected."
            )
        return (value,)


NODE_CLASS_MAPPINGS = {
    "QualityModeSwitch": QualityModeSwitch,
    "LazySwitch": LazySwitch,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "QualityModeSwitch": "Quality Mode Switch",
    "LazySwitch": "Lazy Switch (Any)",
}
