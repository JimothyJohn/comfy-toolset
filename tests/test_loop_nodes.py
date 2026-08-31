import pytest

import loop_nodes
from loop_nodes import (
    LOOP_NODE_CLASS_MAPPINGS,
    NUM_SLOTS,
    RepeatClose,
    RepeatOpen,
)


class FakeGraphNode:
    def __init__(self, class_type, node_id):
        self.class_type = class_type
        self.id = node_id
        self.inputs = {}
        self.display_id = None

    def set_input(self, key, value):
        self.inputs[key] = value

    def set_override_display_id(self, display_id):
        self.display_id = display_id

    def out(self, index):
        return [self.id, index]


class FakeGraphBuilder:
    """Mirrors the GraphBuilder surface RepeatClose uses."""

    def __init__(self):
        self.nodes = {}

    def node(self, class_type, node_id=None):
        node = FakeGraphNode(class_type, node_id)
        self.nodes[node_id] = node
        return node

    def lookup_node(self, node_id):
        return self.nodes[node_id]

    def finalize(self):
        return {
            node_id: {"class_type": n.class_type, "inputs": dict(n.inputs)}
            for node_id, n in self.nodes.items()
        }


class FakeDynPrompt:
    def __init__(self, prompt):
        self.prompt = prompt

    def get_node(self, node_id):
        return self.prompt[node_id]


@pytest.fixture(autouse=True)
def fake_graph_builder(monkeypatch):
    monkeypatch.setattr(loop_nodes, "GraphBuilder", FakeGraphBuilder)


def loop_prompt(iterations, remaining=None):
    """Prompt graph: ext -> body <- open; body -> close.

    `ext` feeds the body from outside the loop; `body` doubles the
    loop-carried value0.
    """
    open_inputs = {"iterations": iterations}
    if remaining is not None:
        open_inputs["_remaining"] = remaining
    return {
        "ext": {"class_type": "ExtNode", "inputs": {}},
        "open1": {"class_type": "RepeatOpen", "inputs": open_inputs},
        "body": {
            "class_type": "BodyNode",
            # slot 3 on RepeatOpen is value0
            "inputs": {"x": ["open1", 3], "cond": ["ext", 0]},
        },
        "close1": {
            "class_type": "RepeatClose",
            "inputs": {"flow_control": ["open1", 0], "value0": ["body", 0]},
        },
    }


class TestRepeatOpen:
    def test_registered(self):
        assert LOOP_NODE_CLASS_MAPPINGS["RepeatOpen"] is RepeatOpen
        assert LOOP_NODE_CLASS_MAPPINGS["RepeatClose"] is RepeatClose

    def test_return_arity_matches_names(self):
        assert len(RepeatOpen.RETURN_TYPES) == len(RepeatOpen.RETURN_NAMES)
        assert len(RepeatClose.RETURN_TYPES) == len(RepeatClose.RETURN_NAMES)

    def test_remaining_socket_never_renders_a_widget(self):
        """_remaining must be forceInput: a widget would inject a stale
        literal into every prompt and break first-pass detection."""
        spec = RepeatOpen.INPUT_TYPES()
        assert spec["optional"]["_remaining"][1]["forceInput"] is True

    def test_first_pass_index_zero(self):
        out = RepeatOpen().start(3, value0="seed")
        assert out[1:3] == (0, 3)
        assert out[3] == "seed"

    def test_recursive_pass_index(self):
        out = RepeatOpen().start(5, _remaining=2)
        assert out[1] == 3  # 5 total, 2 remaining -> 0-based index 3

    @pytest.mark.parametrize("value", [0, 0.0, "", [], False])
    def test_falsy_values_carried(self, value):
        out = RepeatOpen().start(2, value0=value)
        assert out[3] == value


class TestRepeatCloseTermination:
    def test_last_pass_returns_values(self):
        dyn = FakeDynPrompt(loop_prompt(iterations=3, remaining=1))
        out = RepeatClose().finish(
            ["open1", 0], dynprompt=dyn, unique_id="close1", value0="final"
        )
        assert out == ("final", None, None, None)

    def test_single_iteration_never_expands(self):
        dyn = FakeDynPrompt(loop_prompt(iterations=1))
        out = RepeatClose().finish(
            ["open1", 0], dynprompt=dyn, unique_id="close1", value0=42
        )
        assert out == (42, None, None, None)


class TestRepeatCloseExpansion:
    def expand(self, iterations=3, remaining=None, **kwargs):
        dyn = FakeDynPrompt(loop_prompt(iterations=iterations, remaining=remaining))
        return RepeatClose().finish(
            ["open1", 0], dynprompt=dyn, unique_id="close1", **kwargs
        )

    def test_expansion_shape(self):
        out = self.expand(value0="carried")
        assert set(out) == {"result", "expand"}
        # Result comes from the clone-of-self, named "Recurse".
        assert out["result"] == tuple(["Recurse", i] for i in range(NUM_SLOTS))

    def test_clone_open_gets_decremented_counter_and_carried_values(self):
        out = self.expand(iterations=3, value0="carried")
        clone_open = out["expand"]["open1"]
        assert clone_open["inputs"]["_remaining"] == 2
        assert clone_open["inputs"]["value0"] == "carried"
        assert clone_open["inputs"]["iterations"] == 3

    def test_internal_links_remapped_external_links_kept(self):
        out = self.expand()
        body = out["expand"]["body"]
        # open1 is inside the loop: remapped to the clone's output.
        assert body["inputs"]["x"] == ["open1", 3]
        # ext is outside the loop: link kept verbatim to the original node.
        assert body["inputs"]["cond"] == ["ext", 0]
        assert "ext" not in out["expand"]

    def test_contained_covers_open_body_close_only(self):
        out = self.expand()
        assert set(out["expand"]) == {"open1", "body", "Recurse"}


class TestRepeatCloseErrors:
    def test_requires_executor_context(self):
        with pytest.raises(RuntimeError, match="dynprompt"):
            RepeatClose().finish(["open1", 0])

    def test_flow_control_must_be_link(self):
        dyn = FakeDynPrompt(loop_prompt(2))
        with pytest.raises(ValueError, match="flow_control"):
            RepeatClose().finish("bogus", dynprompt=dyn, unique_id="close1")

    def test_flow_control_must_point_at_repeat_open(self):
        dyn = FakeDynPrompt(loop_prompt(2))
        with pytest.raises(ValueError, match="not connected to a Repeat Open"):
            RepeatClose().finish(["ext", 0], dynprompt=dyn, unique_id="close1")

    def test_linked_iterations_rejected(self):
        prompt = loop_prompt(2)
        prompt["open1"]["inputs"]["iterations"] = ["ext", 0]
        dyn = FakeDynPrompt(prompt)
        with pytest.raises(ValueError, match="widget value"):
            RepeatClose().finish(["open1", 0], dynprompt=dyn, unique_id="close1")


class TestFullLoopSimulation:
    """Drive the open/close pair the way the executor would, interpreting
    each expansion, and assert the loop contract: the body runs exactly
    `iterations` times and the carried value threads through every pass."""

    @pytest.mark.parametrize("iterations", [1, 2, 3, 7])
    def test_body_runs_exactly_n_times(self, iterations):
        body_runs = 0
        remaining = None
        value = 1  # body doubles it each pass

        while True:
            open_out = RepeatOpen().start(
                iterations,
                _remaining=remaining,
                value0=value,
            )
            assert open_out[1] == body_runs  # index matches pass count
            value = open_out[3] * 2
            body_runs += 1

            dyn = FakeDynPrompt(loop_prompt(iterations, remaining=remaining))
            out = RepeatClose().finish(
                ["open1", 0], dynprompt=dyn, unique_id="close1", value0=value
            )
            if isinstance(out, tuple):
                break
            clone_open = out["expand"]["open1"]
            remaining = clone_open["inputs"]["_remaining"]
            value = clone_open["inputs"]["value0"]

        assert body_runs == iterations
        assert out[0] == 2**iterations
