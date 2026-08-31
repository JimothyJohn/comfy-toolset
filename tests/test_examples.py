"""Structural checks on the example workflow JSONs.

The examples were generated and load-verified by the real ComfyUI
frontend; these tests keep them from rotting: every referenced node type
must still exist (pack, core, subgraph definition, or a declared
third-party pack), and the link table must stay coherent.
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
    "PrimitiveStringMultiline",
    "PrimitiveBoolean",
    "PrimitiveFloat",
    "PrimitiveInt",
    "PreviewAny",
    "StringConcatenate",
    "LoadImage",
    "LoadAudio",
    "ImageBatch",
    "ImageFromBatch",
    "ImageScaleToTotalPixels",
    "GetImageSize",
    "ResolutionSelector",
    "GetVideoComponents",
    "CreateVideo",
    "SaveVideo",
    "MinimaxHailuo03FirstLastFrameNode",
    "MiniMaxH3ImageToVideo",
    "MiniMaxH3ReferenceToVideo",
    "UNETLoader",
    "CLIPLoader",
    "VAELoader",
    "VAEDecode",
    "VAEDecodeAudio",
    "KSamplerSelect",
    "BasicScheduler",
    "BasicGuider",
    "SamplerCustomAdvanced",
    "RandomNoise",
    "LoraLoaderModelOnly",
    "ComfySwitchNode",
    "ComfyMathExpression",
}

# Types provided by other custom node packs the examples opt into;
# the in-canvas READ ME must name the pack.
THIRD_PARTY_TYPES = {
    "FILM VFI",  # ComfyUI-Frame-Interpolation
}

EXAMPLE_FILES = sorted(EXAMPLES_DIR.glob("*.json"))


def _subgraphs(data):
    return (data.get("definitions") or {}).get("subgraphs", [])


def test_examples_exist():
    names = {path.stem for path in EXAMPLE_FILES}
    assert {
        "repeat-loop-demo",
        "quality-mode-switch",
        "quick-check-final-render",
        "minimax-h3-shot-chain",
        "minimax-h3-ref2va-subgraph",
    } <= names


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda p: p.stem)
class TestExampleStructure:
    def test_parses_with_nodes_and_links(self, path):
        data = json.loads(path.read_text())
        assert data["nodes"], "workflow has no nodes"
        assert data["links"], "workflow has no links"

    def test_only_known_node_types(self, path):
        data = json.loads(path.read_text())
        subgraph_ids = {s["id"] for s in _subgraphs(data)}
        allowed = PACK_TYPES | CORE_TYPES | THIRD_PARTY_TYPES | subgraph_ids
        types = {node["type"] for node in data["nodes"]}
        for sub in _subgraphs(data):
            types |= {node["type"] for node in sub["nodes"]}
        unknown = types - allowed
        assert not unknown, f"unrecognized node types: {unknown}"
        assert types & PACK_TYPES, "example uses no comfy-toolset nodes"

    def test_link_table_coherent(self, path):
        data = json.loads(path.read_text())
        node_ids = {node["id"] for node in data["nodes"]}
        for link in data["links"]:
            link_id, origin, _oslot, target, _tslot, _type = link[:6]
            assert origin in node_ids, f"link {link_id} origin {origin} missing"
            assert target in node_ids, f"link {link_id} target {target} missing"

    def test_has_readme_note(self, path):
        data = json.loads(path.read_text())
        notes = [n for n in data["nodes"] if n["type"] == "MarkdownNote"]
        assert notes, "example lacks its READ ME note"
        texts = [n.get("widgets_values", [""])[0] for n in notes]
        assert any(t and t.strip() for t in texts), "all notes are empty"

    def test_third_party_types_are_documented(self, path):
        """If an example reaches for a third-party pack, its notes must
        say so — 'works out of the box' includes knowing what to install."""
        data = json.loads(path.read_text())
        types = {node["type"] for node in data["nodes"]}
        for sub in _subgraphs(data):
            types |= {node["type"] for node in sub["nodes"]}
        if "FILM VFI" in types:
            notes = " ".join(
                n.get("widgets_values", [""])[0] or ""
                for n in data["nodes"]
                if n["type"] == "MarkdownNote"
            )
            assert "ComfyUI-Frame-Interpolation" in notes
