"""Read Schema.org Recipe microdata without executing a page or using selectors."""
from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
_BLOCKS = {"br", "div", "li", "p", "section", "ol", "ul"}
_REPEATED = {"recipeIngredient", "ingredients", "recipeInstructions", "itemListElement"}


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str | None] = field(default_factory=dict)
    children: list[_Node | str] = field(default_factory=list)


class _Document(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("document")
        self.stack = [self.root]
        self.elements = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.elements += 1
        if self.elements > 50_000 or len(self.stack) > 256:
            raise ValueError("Recipe microdata exceeds the parsing size or nesting limit")
        # HTML permits omitted closing tags for list items and paragraphs.
        if tag in {"li", "p", "dt", "dd"} and self.stack[-1].tag == tag:
            self.stack.pop()
        node = _Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def _types(node: _Node) -> list[str]:
    values = (node.attrs.get("itemtype") or "").split()
    return [value.rstrip("/").rsplit("/", 1)[-1] for value in values
            if value.startswith(("https://schema.org/", "http://schema.org/"))]


def _text(node: _Node) -> str:
    pieces: list[str] = []
    for child in node.children:
        if isinstance(child, str):
            pieces.append(child)
        elif child.tag not in {"script", "style", "template"} and "itemscope" not in child.attrs:
            if child.tag in _BLOCKS:
                pieces.append("\n")
            pieces.append(_text(child))
            if child.tag in _BLOCKS:
                pieces.append("\n")
    return "\n".join(line for raw in "".join(pieces).splitlines() if (line := " ".join(raw.split())))


def _value(node: _Node, prop: str):
    if "itemscope" in node.attrs:
        return _scope(node)
    if node.tag == "meta":
        return node.attrs.get("content") or ""
    if node.tag in {"img", "audio", "video", "source", "embed", "iframe", "track"}:
        return node.attrs.get("src") or ""
    if node.tag in {"a", "area", "link"}:
        return node.attrs.get("href") or ""
    if node.tag == "time" and node.attrs.get("datetime"):
        return node.attrs["datetime"]
    if node.tag in {"data", "meter"} and node.attrs.get("value"):
        return node.attrs["value"]
    if prop == "recipeInstructions":
        properties = _properties(node)
        steps = properties.get("itemListElement") or properties.get("recipeInstructions")
        if steps:
            return {"@type": "HowToSection", "itemListElement": steps}
    return _text(node)


def _properties(node: _Node) -> dict:
    collected: dict[str, list] = {}

    def visit(parent: _Node) -> None:
        for child in parent.children:
            if isinstance(child, str) or child.tag in {"script", "style", "template"}:
                continue
            props = (child.attrs.get("itemprop") or "").split()
            if props:
                # A nested recommendation must not supply the current recipe's fields.
                if "Recipe" in _types(child):
                    continue
                for prop in props:
                    value = _value(child, prop)
                    if value:
                        collected.setdefault(prop, []).append(value)
            elif "itemscope" not in child.attrs:
                visit(child)

    visit(node)
    return {prop: values if prop in _REPEATED or len(values) > 1 else values[0]
            for prop, values in collected.items()}


def _scope(node: _Node) -> dict:
    result = _properties(node)
    types = _types(node)
    if types:
        result["@type"] = types[0] if len(types) == 1 else types
    return result


def find_microdata_recipe(page: str) -> dict | None:
    """Return the first complete top-level Recipe, or its first incomplete candidate.

    Only itemprop/itemscope markup is interpreted. Generic visible HTML, RDFa,
    JavaScript data and itemref links outside the scope are not inferred.
    """
    parser = _Document()
    parser.feed(page)
    candidates: list[dict] = []

    def visit(node: _Node) -> None:
        if node.tag in {"script", "style", "template"}:
            return
        if "itemscope" in node.attrs and "Recipe" in _types(node):
            candidates.append(_scope(node))
            return
        for child in node.children:
            if isinstance(child, _Node):
                visit(child)

    visit(parser.root)
    for candidate in candidates:
        if candidate.get("name") and candidate.get("recipeIngredient") and candidate.get("recipeInstructions"):
            return candidate
    return candidates[0] if candidates else None
