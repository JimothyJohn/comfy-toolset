import pytest

from nodes import (
    ANY,
    NODE_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS,
    LazySwitch,
    QualityModeSwitch,
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
    "final_fps": 24.0,
    "final_frames": 121,
    "final_steps": 30,
    "final_cfg": 3.5,
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
        assert out == (DRAFT, 16.0, 33, 4, 1.0, False)
        assert out[0] is DRAFT

    def test_final_mode(self):
        out = QualityModeSwitch().route(
            True, **NUMERIC_ARGS, draft_model=DRAFT, final_model=FINAL
        )
        assert out == (FINAL, 24.0, 121, 30, 3.5, True)
        assert out[0] is FINAL

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
