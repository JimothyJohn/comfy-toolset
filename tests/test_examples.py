"""Structural checks on the example workflow JSONs.

The examples were generated and execution-verified by the real ComfyUI
frontend; these tests keep them from rotting: every referenced node type
must still exist (pack or core), and the link table must stay coherent.
"""

import json
from pathlib import Path

import pytest

from loop_nodes import LOOP_NODE_CLASS_MAPPINGS
from nodes import NODE_CLASS_MAPPINGS as BASE_MAPPINGS

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"
PACK_TYPES = set(BASE_MAPPINGS) | set(LOOP_NODE_CLASS_MAPPINGS)

# Core node types the examples are allowed to reference. Additions here
# should be verified against ComfyUI before extending an example.
CORE_TYPES = {
    "MarkdownNote",
    "PrimitiveString",
    "PreviewAny",
    "StringConcatenate",
    "CheckpointLoaderSimple",
    "LoraLoader",
    "CLIPTextEncode",
    "EmptyLatentImage",
    "KSampler",
    "VAEDecode",
    "SaveImage",
    "LoadImage",
    "MinimaxHailuo03FirstLastFrameNode",
    "GetVideoComponents",
    "ImageFromBatch",
    "ImageBatch",
    "CreateVideo",
    "SaveVideo",
}

EXAMPLE_FILES = sorted(EXAMPLES_DIR.glob("*.json"))


def test_examples_exist():
    names = {path.stem for path in EXAMPLE_FILES}
    assert {"repeat-loop-demo", "quality-mode-switch", "minimax-h3-shot-chain"} <= names


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda p: p.stem)
class TestExampleStructure:
    def test_parses_with_nodes_and_links(self, path):
        data = json.loads(path.read_text())
        assert data["nodes"], "workflow has no nodes"
        assert data["links"], "workflow has no links"

    def test_only_known_node_types(self, path):
        data = json.loads(path.read_text())
        types = {node["type"] for node in data["nodes"]}
        unknown = types - PACK_TYPES - CORE_TYPES
        assert not unknown, f"unrecognized node types: {unknown}"
        assert types & PACK_TYPES, "example uses no comfy-toolset nodes"

    def test_link_table_coherent(self, path):
        data = json.loads(path.read_text())
        node_ids = {node["id"] for node in data["nodes"]}
        for link in data["links"]:
            link_id, origin, _origin_slot, target, _target_slot, _type = link[:6]
            assert origin in node_ids, f"link {link_id} origin {origin} missing"
            assert target in node_ids, f"link {link_id} target {target} missing"

    def test_has_readme_note(self, path):
        data = json.loads(path.read_text())
        notes = [n for n in data["nodes"] if n["type"] == "MarkdownNote"]
        assert notes, "example lacks its READ ME note"
        assert notes[0].get("widgets_values", [""])[0].strip(), "note is empty"
