"""
PubMed-like query parsing for PostgreSQL FTS (tiab).

Goal: accept a small, predictable subset of PubMed boolean syntax and compile it
to a PostgreSQL `tsquery` string that can be passed to:
  to_tsquery('english', unaccent(:kw))

Supported (case-insensitive):
- Boolean: AND / OR / NOT  (also accepts &, |, !)
- Grouping: parentheses ( )
- Phrase: "quoted phrase"  -> uses `<->` adjacency
- Prefix wildcard: word*    -> uses `:*`
- Field tags: [tiab] or [Title/Abstract] (ignored; only tiab supported)

Not supported:
- Per-subexpression field scoping (e.g. term[ti] mixed with term[ab])
- MeSH tags ([mh]), proximity operators, range syntax, etc.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, List, Optional


class QueryParseError(ValueError):
    """Raised when a query cannot be parsed/compiled safely."""


@dataclass(frozen=True)
class _Token:
    kind: str
    value: Optional[str] = None


_K_TERM = "TERM"
_K_AND = "AND"
_K_OR = "OR"
_K_NOT = "NOT"
_K_LPAREN = "LPAREN"
_K_RPAREN = "RPAREN"
_K_FIELD = "FIELD"

_BOOL_WORDS = {"AND": _K_AND, "OR": _K_OR, "NOT": _K_NOT}
_SUPPORTED_FIELD_TAGS = {"tiab", "title/abstract"}


def pubmed_tiab_to_tsquery(query: str) -> str:
    """
    Convert a PubMed-like boolean query to a PostgreSQL tsquery string (tiab).

    Args:
        query: User-provided PubMed-like query.

    Returns:
        A tsquery string using &, |, !, <-> and parentheses.

    Raises:
        QueryParseError: If the query is invalid or uses unsupported features.
    """
    if query is None:
        raise QueryParseError("Empty query")
    raw = _collapse_ws(query)
    if not raw:
        raise QueryParseError("Empty query")

    tokens = _tokenize_pubmed_like(raw)
    tokens = _strip_and_validate_field_tags(tokens)
    tokens = _insert_implicit_and(tokens)
    if not tokens:
        raise QueryParseError("Empty query")

    rpn = _to_rpn(tokens)
    return _rpn_to_tsquery(rpn)


def _collapse_ws(text: str) -> str:
    # Keep punctuation; only normalize whitespace/control chars.
    cleaned = re.sub(r"[\u0000-\u001f]+", " ", text)
    return re.sub(r"\s+", " ", cleaned).strip()


def _tokenize_pubmed_like(text: str) -> List[_Token]:
    tokens: List[_Token] = []
    index = 0
    length = len(text)

    while index < length:
        ch = text[index]

        if ch.isspace():
            index += 1
            continue

        if ch == '"':
            end = _find_closing_quote(text, index + 1)
            if end is None:
                raise QueryParseError('Unclosed quote (")')
            phrase = text[index + 1 : end]
            term = _phrase_to_tsquery(phrase)
            if term:
                tokens.append(_Token(_K_TERM, term))
            index = end + 1
            continue

        if ch == "(":
            tokens.append(_Token(_K_LPAREN))
            index += 1
            continue

        if ch == ")":
            tokens.append(_Token(_K_RPAREN))
            index += 1
            continue

        if ch == "&":
            tokens.append(_Token(_K_AND))
            index += 1
            continue

        if ch == "|":
            tokens.append(_Token(_K_OR))
            index += 1
            continue

        if ch == "!":
            tokens.append(_Token(_K_NOT))
            index += 1
            continue

        if ch == "[":
            end = text.find("]", index + 1)
            if end == -1:
                raise QueryParseError("Unclosed field tag ([...])")
            tag = text[index + 1 : end].strip()
            if tag:
                tokens.append(_Token(_K_FIELD, tag))
            index = end + 1
            continue

        # Consume a word-like chunk until a structural delimiter.
        start = index
        while index < length and (not text[index].isspace()) and text[index] not in '()[]"':
            index += 1
        chunk = text[start:index]
        if not chunk:
            continue

        upper = chunk.upper()
        if upper in _BOOL_WORDS:
            tokens.append(_Token(_BOOL_WORDS[upper]))
            continue

        term = _raw_term_to_tsquery(chunk)
        if term:
            tokens.append(_Token(_K_TERM, term))

    return tokens


def _find_closing_quote(text: str, start: int) -> Optional[int]:
    # Support backslash-escaped quotes: \" (best-effort).
    index = start
    while index < len(text):
        if text[index] == '"':
            # Count preceding backslashes to determine if escaped.
            backslashes = 0
            j = index - 1
            while j >= 0 and text[j] == "\\":
                backslashes += 1
                j -= 1
            if backslashes % 2 == 0:
                return index
        index += 1
    return None


def _strip_and_validate_field_tags(tokens: Iterable[_Token]) -> List[_Token]:
    cleaned: List[_Token] = []
    for tok in tokens:
        if tok.kind != _K_FIELD:
            cleaned.append(tok)
            continue
        tag = (tok.value or "").strip().lower()
        if not tag:
            continue
        if tag not in _SUPPORTED_FIELD_TAGS:
            raise QueryParseError(f"Unsupported field tag [{tag}]; only [tiab] is supported")
        # Ignore tiab tags (query is already tiab-only)
    return cleaned


def _insert_implicit_and(tokens: List[_Token]) -> List[_Token]:
    """
    PubMed treats adjacency as AND. Insert AND where needed:
      TERM )  followed by  TERM ( NOT
    """
    out: List[_Token] = []
    prev: Optional[_Token] = None
    for tok in tokens:
        if prev is not None and _needs_implicit_and(prev, tok):
            out.append(_Token(_K_AND))
        out.append(tok)
        prev = tok
    return out


def _needs_implicit_and(prev: _Token, curr: _Token) -> bool:
    prev_is_operand = prev.kind in (_K_TERM, _K_RPAREN)
    curr_is_operand_start = curr.kind in (_K_TERM, _K_LPAREN, _K_NOT)
    return prev_is_operand and curr_is_operand_start


def _raw_term_to_tsquery(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""

    # Prefix wildcard: only support trailing "*"
    wildcard = raw.endswith("*")
    if wildcard:
        raw = raw[:-1]

    lexemes = re.findall(r"\w+", raw)
    if not lexemes:
        return ""

    compiled: List[str] = []
    for idx, lex in enumerate(lexemes):
        if not lex:
            continue
        is_last = idx == len(lexemes) - 1
        if wildcard and is_last:
            compiled.append(f"{lex}:*")
        else:
            compiled.append(lex)

    if not compiled:
        return ""
    if len(compiled) == 1:
        return compiled[0]
    return "(" + " <-> ".join(compiled) + ")"


def _phrase_to_tsquery(phrase: str) -> str:
    # Keep word characters, allow each word to have trailing '*'.
    raw_terms = re.findall(r"\w+\*?", phrase)
    compiled: List[str] = []
    for raw in raw_terms:
        raw = raw.strip()
        if not raw:
            continue
        if raw.endswith("*"):
            word = raw[:-1]
            if word:
                compiled.append(f"{word}:*")
        else:
            compiled.append(raw)

    if not compiled:
        return ""
    if len(compiled) == 1:
        return compiled[0]
    return "(" + " <-> ".join(compiled) + ")"


def _to_rpn(tokens: List[_Token]) -> List[_Token]:
    """
    Shunting-yard to convert tokens to RPN.
    Precedence: NOT > AND > OR
    """
    output: List[_Token] = []
    stack: List[_Token] = []

    for tok in tokens:
        if tok.kind == _K_TERM:
            output.append(tok)
            continue

        if tok.kind in (_K_AND, _K_OR, _K_NOT):
            while stack and stack[-1].kind in (_K_AND, _K_OR, _K_NOT):
                top = stack[-1]
                if _should_pop_operator(top, tok):
                    output.append(stack.pop())
                else:
                    break
            stack.append(tok)
            continue

        if tok.kind == _K_LPAREN:
            stack.append(tok)
            continue

        if tok.kind == _K_RPAREN:
            found = False
            while stack:
                top = stack.pop()
                if top.kind == _K_LPAREN:
                    found = True
                    break
                output.append(top)
            if not found:
                raise QueryParseError("Unbalanced parentheses")
            continue

        raise QueryParseError(f"Unsupported token: {tok.kind}")

    while stack:
        top = stack.pop()
        if top.kind in (_K_LPAREN, _K_RPAREN):
            raise QueryParseError("Unbalanced parentheses")
        output.append(top)

    return output


def _precedence(kind: str) -> int:
    if kind == _K_NOT:
        return 3
    if kind == _K_AND:
        return 2
    if kind == _K_OR:
        return 1
    return 0


def _is_right_associative(kind: str) -> bool:
    return kind == _K_NOT


def _should_pop_operator(stack_op: _Token, incoming: _Token) -> bool:
    sp = _precedence(stack_op.kind)
    ip = _precedence(incoming.kind)
    if sp > ip:
        return True
    if sp < ip:
        return False
    # Equal precedence
    return not _is_right_associative(incoming.kind)


def _rpn_to_tsquery(rpn: List[_Token]) -> str:
    stack: List[str] = []

    for tok in rpn:
        if tok.kind == _K_TERM:
            stack.append(tok.value or "")
            continue

        if tok.kind == _K_NOT:
            if not stack:
                raise QueryParseError("Invalid query: NOT missing operand")
            operand = stack.pop()
            stack.append(f"!({operand})")
            continue

        if tok.kind in (_K_AND, _K_OR):
            if len(stack) < 2:
                raise QueryParseError("Invalid query: boolean operator missing operand")
            right = stack.pop()
            left = stack.pop()
            op = "&" if tok.kind == _K_AND else "|"
            stack.append(f"({left} {op} {right})")
            continue

        raise QueryParseError(f"Unsupported token in RPN: {tok.kind}")

    if not stack:
        raise QueryParseError("Empty query")
    if len(stack) != 1:
        raise QueryParseError("Invalid query: trailing operands/operators")
    return stack[0]

