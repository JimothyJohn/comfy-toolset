"""Comfy Toolset — minimal workflow-switching nodes for ComfyUI.

Zero runtime dependencies. Nothing in this module imports ComfyUI itself;
the only API surface is the node-definition contract (INPUT_TYPES,
RETURN_TYPES, check_lazy_status), which keeps these nodes importable and
testable anywhere and resilient to ComfyUI-internal refactors.

Bypass mechanism: inputs marked ``"lazy": True`` are only evaluated when
``check_lazy_status`` asks for them, so everything upstream of the
unselected branch (LoRA loaders included) is never executed at all.
"""

import logging

logger = logging.getLogger("comfy-toolset")


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
    RETURN_TYPES = (
        "MODEL",
        "FLOAT",
        "INT",
        "INT",
        "FLOAT",
        "BOOLEAN",
        "FLOAT",
        "FLOAT",
        "BOOLEAN",
    )
    RETURN_NAMES = (
        "model",
        "fps",
        "frames",
        "steps",
        "cfg",
        "is_final",
        "seconds",
        "megapixels",
        "is_draft",
    )

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
                "draft_seconds": (
                    "FLOAT",
                    {"default": 4.0, "min": 0.1, "max": 3600.0, "step": 0.1},
                ),
                "draft_megapixels": (
                    "FLOAT",
                    {"default": 0.2, "min": 0.01, "max": 16.0, "step": 0.01},
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
                "final_seconds": (
                    "FLOAT",
                    {"default": 9.0, "min": 0.1, "max": 3600.0, "step": 0.1},
                ),
                "final_megapixels": (
                    "FLOAT",
                    {"default": 0.9, "min": 0.01, "max": 16.0, "step": 0.01},
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
        draft_seconds,
        draft_megapixels,
        final_fps,
        final_frames,
        final_steps,
        final_cfg,
        final_seconds,
        final_megapixels,
        draft_model=None,
        final_model=None,
    ):
        model = final_model if mode else draft_model
        if model is None:
            which = "final_model" if mode else "draft_model"
            hint = (
                "connect your clean (no-LoRA) model to 'final_model'"
                if mode
                else "connect your LoRA-patched model to 'draft_model'"
            )
            raise ValueError(
                f"QualityModeSwitch: mode is '{'final' if mode else 'draft'}' "
                f"but nothing is connected to '{which}' — {hint}, or flip the "
                "mode toggle."
            )
        if mode:
            logger.info(
                "[Quality Mode Switch] FINAL mode: fps=%s frames=%s steps=%s "
                "cfg=%s seconds=%s megapixels=%s (draft branch bypassed — its "
                "LoRA chain never runs)",
                final_fps,
                final_frames,
                final_steps,
                final_cfg,
                final_seconds,
                final_megapixels,
            )
            return (
                model,
                final_fps,
                final_frames,
                final_steps,
                final_cfg,
                True,
                final_seconds,
                final_megapixels,
                False,
            )
        logger.info(
            "[Quality Mode Switch] DRAFT mode: fps=%s frames=%s steps=%s "
            "cfg=%s seconds=%s megapixels=%s (final branch bypassed)",
            draft_fps,
            draft_frames,
            draft_steps,
            draft_cfg,
            draft_seconds,
            draft_megapixels,
        )
        return (
            model,
            draft_fps,
            draft_frames,
            draft_steps,
            draft_cfg,
            False,
            draft_seconds,
            draft_megapixels,
            True,
        )


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
            picked = "b" if pick_b else "a"
            raise ValueError(
                f"LazySwitch: input '{picked}' is selected but not connected "
                f"— wire something into '{picked}' or flip the toggle to "
                f"'{'a' if pick_b else 'b'}'."
            )
        logger.info(
            "[Lazy Switch] picked '%s' (%s); other branch bypassed",
            "b" if pick_b else "a",
            type(value).__name__,
        )
        return (value,)


class SubjectPrompt:
    """Auto-number reference pictures per subject and build the prompt.

    Feed each subject's sample images (up to 4 per subject) and
    optionally the previous shot's last frame. Connected images are
    compacted in order into ``picture1..picture9`` (matching MiniMax
    H3's ``<Picture i>`` numbering, which skips empty slots), and the
    ``prompt`` output opens with the matching reference lines — so
    adding or removing a sample renumbers everything automatically.

    Wire picture1..picture9 straight into the H3 ref_image slots and
    ``prompt`` into its prompt input; unused picture outputs carry
    nothing and H3 ignores them.
    """

    CATEGORY = "toolset"
    FUNCTION = "build"
    MAX_PER_SUBJECT = 4
    MAX_PICTURES = 9

    RETURN_TYPES = ("STRING",) + ("IMAGE",) * MAX_PICTURES + ("INT",)
    RETURN_NAMES = (
        ("prompt",)
        + tuple(f"picture{i}" for i in range(1, MAX_PICTURES + 1))
        + ("picture_count",)
    )

    @classmethod
    def INPUT_TYPES(cls):
        optional = {}
        for subject in (1, 2):
            for i in range(1, cls.MAX_PER_SUBJECT + 1):
                optional[f"subject{subject}_image{i}"] = ("IMAGE",)
        optional["prev_frame"] = ("IMAGE",)
        return {
            "required": {
                "scene": ("STRING", {"default": "", "multiline": True}),
                "subject1_desc": ("STRING", {"default": "Subject 1"}),
                "subject2_desc": ("STRING", {"default": "Subject 2"}),
            },
            "optional": optional,
        }

    def build(self, scene, subject1_desc, subject2_desc, prev_frame=None, **kwargs):
        pictures = []
        lines = []
        for subject, desc in ((1, subject1_desc), (2, subject2_desc)):
            numbers = []
            for i in range(1, self.MAX_PER_SUBJECT + 1):
                image = kwargs.get(f"subject{subject}_image{i}")
                if image is None:
                    continue
                pictures.append(image)
                numbers.append(len(pictures))
            if numbers:
                tags = ", ".join(f"<Picture {n}>" for n in numbers)
                label = desc.strip() or f"Subject {subject}"
                lines.append(f"{label}: {tags}.")
        if prev_frame is not None:
            pictures.append(prev_frame)
            lines.append(
                f"<Picture {len(pictures)}> is the last frame of the previous "
                "shot; continue seamlessly from it into a new shot."
            )
        if len(pictures) > self.MAX_PICTURES:
            raise ValueError(
                f"SubjectPrompt: {len(pictures)} reference pictures connected "
                f"but MiniMax H3 supports at most {self.MAX_PICTURES}."
            )
        parts = lines + ([scene.strip()] if scene.strip() else [])
        prompt = "\n".join(parts)
        logger.info(
            "[Subject Prompt] %d picture(s) assigned: %s",
            len(pictures),
            " | ".join(lines) if lines else "none",
        )
        padded = pictures + [None] * (self.MAX_PICTURES - len(pictures))
        return (prompt, *padded, len(pictures))


class RenderMode:
    """Quick check or final render — the two-control switch.

    Everything not directly tied to the output is preset: quick check
    runs 0.2 MP with the Lightning LoRA, capped at 4 s, no
    interpolation; final render runs 0.9 MP with the full model at your
    requested length, FILM-interpolated ×2 to 48 fps. You touch two
    things: the mode toggle and how long the final render should be.

    Wire the outputs once — ``megapixels`` to the resolution scaler,
    ``seconds`` to the duration input, ``lightning_lora`` to the H3
    subgraph's Enable Lightning LoRA, ``is_final`` to the LazySwitch
    gating the interpolator, ``fps`` to Create Video, and
    ``filename_prefix`` to Save Video so quick checks and finals never
    overwrite each other. QualityModeSwitch remains the fully
    adjustable generic alternative.
    """

    CATEGORY = "toolset"
    FUNCTION = "route"

    QUICK_MEGAPIXELS = 0.2
    FINAL_MEGAPIXELS = 0.9
    QUICK_MAX_SECONDS = 4.0
    BASE_FPS = 24.0
    INTERPOLATION_MULTIPLIER = 2
    QUICK_PREFIX = "video/quick-check"
    FINAL_PREFIX = "video/final-render"

    RETURN_TYPES = ("FLOAT", "FLOAT", "FLOAT", "BOOLEAN", "BOOLEAN", "STRING")
    RETURN_NAMES = (
        "seconds",
        "megapixels",
        "fps",
        "lightning_lora",
        "is_final",
        "filename_prefix",
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mode": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "label_on": "final render",
                        "label_off": "quick check",
                    },
                ),
                "seconds": (
                    "FLOAT",
                    {
                        "default": 9.0,
                        "min": 0.1,
                        "max": 3600.0,
                        "step": 0.1,
                        "tooltip": "Final render length. Quick checks are "
                        f"automatically capped at {cls.QUICK_MAX_SECONDS:g}s.",
                    },
                ),
            },
        }

    def route(self, mode, seconds):
        if mode:
            fps = self.BASE_FPS * self.INTERPOLATION_MULTIPLIER
            logger.info(
                "[Render Mode] FINAL RENDER: %.1fs @ %.1fMP, full model, "
                "interpolated x%d -> %.0f fps",
                seconds,
                self.FINAL_MEGAPIXELS,
                self.INTERPOLATION_MULTIPLIER,
                fps,
            )
            return (
                seconds,
                self.FINAL_MEGAPIXELS,
                fps,
                False,
                True,
                self.FINAL_PREFIX,
            )
        quick_seconds = min(seconds, self.QUICK_MAX_SECONDS)
        logger.info(
            "[Render Mode] QUICK CHECK: %.1fs @ %.1fMP, lightning LoRA, "
            "no interpolation (%.0f fps)",
            quick_seconds,
            self.QUICK_MEGAPIXELS,
            self.BASE_FPS,
        )
        return (
            quick_seconds,
            self.QUICK_MEGAPIXELS,
            self.BASE_FPS,
            True,
            False,
            self.QUICK_PREFIX,
        )


NODE_CLASS_MAPPINGS = {
    "QualityModeSwitch": QualityModeSwitch,
    "LazySwitch": LazySwitch,
    "SubjectPrompt": SubjectPrompt,
    "RenderMode": RenderMode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "QualityModeSwitch": "Quality Mode Switch",
    "LazySwitch": "Lazy Switch (Any)",
    "SubjectPrompt": "Subject Prompt (H3 refs)",
    "RenderMode": "Render Mode (quick check / final render)",
}
