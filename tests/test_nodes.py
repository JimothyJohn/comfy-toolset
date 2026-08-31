import pytest

from nodes import (
    ANY,
    NODE_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS,
    LazySwitch,
    QualityModeSwitch,
    SubjectPrompt,
)


class FakeModel:
    """Stand-in for a ComfyUI MODEL object; the switch must not touch it."""


DRAFT = FakeModel()
FINAL = FakeModel()

NUMERIC_ARGS = {
    "draft_fps": 16.0,
    "draft_frames": 33,
    "draft_steps": 4,
    "draft_cfg": 1.0,
    "draft_seconds": 4.0,
    "draft_megapixels": 0.2,
    "final_fps": 24.0,
    "final_frames": 121,
    "final_steps": 30,
    "final_cfg": 3.5,
    "final_seconds": 9.0,
    "final_megapixels": 0.9,
}


class TestAnyType:
    def test_never_unequal(self):
        # `!=` is what ComfyUI's link validation uses; it must always be False.
        assert (ANY != "MODEL") is False
        assert (ANY != "IMAGE") is False
        assert (ANY != "") is False

    def test_is_wildcard_string(self):
        assert str(ANY) == "*"
        assert isinstance(ANY, str)


class TestQualityModeSwitchContract:
    def test_registered(self):
        assert NODE_CLASS_MAPPINGS["QualityModeSwitch"] is QualityModeSwitch
        assert "QualityModeSwitch" in NODE_DISPLAY_NAME_MAPPINGS

    def test_model_inputs_are_lazy_and_optional(self):
        spec = QualityModeSwitch.INPUT_TYPES()
        for name in ("draft_model", "final_model"):
            typ, opts = spec["optional"][name]
            assert typ == "MODEL"
            assert opts["lazy"] is True

    def test_return_arity_matches_names(self):
        assert len(QualityModeSwitch.RETURN_TYPES) == len(
            QualityModeSwitch.RETURN_NAMES
        )

    def test_all_declared_inputs_accepted_by_route(self):
        """Every name in INPUT_TYPES must be a parameter of route(),
        since ComfyUI calls FUNCTION with all inputs as kwargs."""
        import inspect

        spec = QualityModeSwitch.INPUT_TYPES()
        params = inspect.signature(QualityModeSwitch.route).parameters
        declared = set(spec["required"]) | set(spec["optional"])
        assert declared <= set(params)


class TestQualityModeSwitchLazy:
    @pytest.mark.parametrize(
        "mode,connected,expected",
        [
            (False, {}, ["draft_model"]),
            (True, {}, ["final_model"]),
            (False, {"draft_model": DRAFT}, []),
            (True, {"final_model": FINAL}, []),
            # The wrong-branch model being available must not satisfy the switch.
            (False, {"final_model": FINAL}, ["draft_model"]),
            (True, {"draft_model": DRAFT}, ["final_model"]),
        ],
    )
    def test_requests_only_selected_branch(self, mode, connected, expected):
        node = QualityModeSwitch()
        assert node.check_lazy_status(mode, **NUMERIC_ARGS, **connected) == expected


class TestQualityModeSwitchRoute:
    def test_draft_mode(self):
        out = QualityModeSwitch().route(
            False, **NUMERIC_ARGS, draft_model=DRAFT, final_model=FINAL
        )
        assert out == (DRAFT, 16.0, 33, 4, 1.0, False, 4.0, 0.2, True)
        assert out[0] is DRAFT

    def test_final_mode(self):
        out = QualityModeSwitch().route(
            True, **NUMERIC_ARGS, draft_model=DRAFT, final_model=FINAL
        )
        assert out == (FINAL, 24.0, 121, 30, 3.5, True, 9.0, 0.9, False)
        assert out[0] is FINAL

    def test_default_widget_values_match_spec(self):
        """The shipped defaults are part of the contract: 4s/0.2MP draft,
        9s/0.9MP final."""
        spec = QualityModeSwitch.INPUT_TYPES()["required"]
        assert spec["draft_seconds"][1]["default"] == 4.0
        assert spec["final_seconds"][1]["default"] == 9.0
        assert spec["draft_megapixels"][1]["default"] == 0.2
        assert spec["final_megapixels"][1]["default"] == 0.9

    def test_new_outputs_appended_not_inserted(self):
        """seconds/megapixels must come after is_final so existing
        workflows keep their output slot indices."""
        assert QualityModeSwitch.RETURN_NAMES[:6] == (
            "model",
            "fps",
            "frames",
            "steps",
            "cfg",
            "is_final",
        )
        assert QualityModeSwitch.RETURN_NAMES[6:] == (
            "seconds",
            "megapixels",
            "is_draft",
        )

    def test_unselected_branch_may_be_none(self):
        out = QualityModeSwitch().route(False, **NUMERIC_ARGS, draft_model=DRAFT)
        assert out[0] is DRAFT

    @pytest.mark.parametrize(
        "mode,missing", [(False, "draft_model"), (True, "final_model")]
    )
    def test_selected_branch_missing_raises(self, mode, missing):
        other = {"final_model" if mode else "draft_model": None}
        connected = {("draft_model" if mode else "final_model"): FakeModel()}
        with pytest.raises(ValueError, match=missing):
            QualityModeSwitch().route(mode, **NUMERIC_ARGS, **other, **connected)


class TestLazySwitch:
    def test_registered(self):
        assert NODE_CLASS_MAPPINGS["LazySwitch"] is LazySwitch

    def test_wildcard_inputs_are_lazy(self):
        spec = LazySwitch.INPUT_TYPES()
        for name in ("a", "b"):
            typ, opts = spec["optional"][name]
            assert (typ != "LATENT") is False  # wildcard matches anything
            assert opts["lazy"] is True

    def test_validate_inputs_skips_type_checking(self):
        assert LazySwitch.VALIDATE_INPUTS(input_types={"a": "IMAGE"}) is True

    @pytest.mark.parametrize(
        "pick_b,kwargs,expected",
        [
            (False, {}, ["a"]),
            (True, {}, ["b"]),
            (False, {"a": 1}, []),
            (True, {"b": 1}, []),
            (False, {"b": 1}, ["a"]),
            (True, {"a": 1}, ["b"]),
        ],
    )
    def test_lazy_status(self, pick_b, kwargs, expected):
        assert LazySwitch().check_lazy_status(pick_b, **kwargs) == expected

    @pytest.mark.parametrize(
        "value",
        [0, 0.0, "", [], {}, False],
        ids=["int0", "float0", "empty-str", "empty-list", "empty-dict", "False"],
    )
    def test_falsy_values_pass_through(self, value):
        """Selection must be `is None`, not truthiness — 0.0 fps or an
        empty list is a legitimate payload."""
        assert LazySwitch().route(False, a=value, b=None) == (value,)
        assert LazySwitch().route(True, a=None, b=value) == (value,)

    @pytest.mark.parametrize("pick_b,missing", [(False, "'a'"), (True, "'b'")])
    def test_selected_missing_raises(self, pick_b, missing):
        with pytest.raises(ValueError, match=missing):
            LazySwitch().route(pick_b, a=None, b=None)


class Img:
    """Stand-in for an image tensor; the node must only check `is None`
    (torch tensors raise on truthiness)."""

    def __bool__(self):
        raise RuntimeError("truthiness must never be evaluated on images")


class TestSubjectPrompt:
    def test_registered(self):
        assert NODE_CLASS_MAPPINGS["SubjectPrompt"] is SubjectPrompt
        assert len(SubjectPrompt.RETURN_TYPES) == len(SubjectPrompt.RETURN_NAMES)

    def test_compacts_and_numbers_across_subjects(self):
        a1, a3, b2, prev = Img(), Img(), Img(), Img()
        out = SubjectPrompt().build(
            "A tense chase across the rooftops.",
            "the red android",
            "the mecha dragon",
            subject1_image1=a1,
            subject1_image3=a3,  # gap: must compact, not leave a hole
            subject2_image2=b2,
            prev_frame=prev,
        )
        prompt, pics, count = out[0], out[1:10], out[10]
        assert count == 4
        assert pics[0] is a1 and pics[1] is a3 and pics[2] is b2 and pics[3] is prev
        assert all(p is None for p in pics[4:])
        assert "the red android: <Picture 1>, <Picture 2>." in prompt
        assert "the mecha dragon: <Picture 3>." in prompt
        assert "<Picture 4> is the last frame of the previous shot" in prompt
        assert prompt.endswith("A tense chase across the rooftops.")

    def test_no_references_yields_scene_only(self):
        out = SubjectPrompt().build("Just a landscape.", "s1", "s2")
        assert out[0] == "Just a landscape."
        assert out[10] == 0
        assert all(p is None for p in out[1:10])

    def test_blank_desc_falls_back_to_subject_number(self):
        out = SubjectPrompt().build("", "  ", "x", subject1_image1=Img())
        assert out[0] == "Subject 1: <Picture 1>."

    def test_full_house_is_exactly_nine(self):
        kwargs = {f"subject{s}_image{i}": Img() for s in (1, 2) for i in range(1, 5)}
        out = SubjectPrompt().build("scene", "A", "B", prev_frame=Img(), **kwargs)
        assert out[10] == 9
        assert all(p is not None for p in out[1:10])
        assert "<Picture 9> is the last frame" in out[0]

    def test_prev_frame_only(self):
        out = SubjectPrompt().build("scene", "A", "B", prev_frame=Img())
        assert "<Picture 1> is the last frame of the previous shot" in out[0]
        assert out[10] == 1

    def test_all_declared_inputs_accepted(self):
        import inspect

        spec = SubjectPrompt.INPUT_TYPES()
        params = inspect.signature(SubjectPrompt.build).parameters
        accepts_kwargs = any(
            p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
        )
        declared = set(spec["required"]) | set(spec["optional"])
        named = {n for n in declared if n in params}
        assert accepts_kwargs and "scene" in named and "prev_frame" in named
