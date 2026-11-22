"""Pure-Python TypeScript-to-ES2022 stripper for Seanime extensions.

Strips compile-time TypeScript syntax while preserving runtime JavaScript
semantics, regex/template literals, comments, and newline positions.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

_IDENT_RE = re.compile(r'[A-Za-z_$][A-Za-z0-9_$]*')
_NUM_RE = re.compile(r'0[xXbBoO][0-9A-Fa-f_]+n?|(?:\d[\d_]*(?:\.[\d_]*)?|\.\d[\d_]*)(?:[eE][+-]?\d[\d_]*)?n?')

_MULTI_PUNCT = (
    '>>>=',
    '===',
    '!==',
    '>>>',
    '>>=',
    '<<=',
    '**=',
    '??=',
    '&&=',
    '||=',
    '...',
    '=>',
    '?.',
    '??',
    '&&',
    '||',
    '**',
    '<<',
    '>>',
    '<=',
    '>=',
    '==',
    '!=',
    '+=',
    '-=',
    '*=',
    '/=',
    '%=',
    '&=',
    '|=',
    '^=',
    '++',
    '--',
)

_REGEX_PREV_WORDS = frozenset({
    'return',
    'throw',
    'case',
    'delete',
    'void',
    'typeof',
    'await',
    'yield',
    'in',
    'of',
    'instanceof',
    'else',
    'do',
    'new',
    'as',
    'satisfies',
    'export',
    'default',
})

_REGEX_PREV_NO_PUNCT = frozenset({')', ']', '++', '--'})

_ACCESS_MODIFIERS = frozenset({'public', 'private', 'protected', 'readonly', 'override'})
_VALUE_BINOPS = frozenset({
    '+', '-', '*', '/', '%', '**', '==', '!=', '===', '!==', '<', '<=', '>', '>=',
    '&&', '||', '??', '&', '|', '^', '<<', '>>', '>>>', '=', '+=', '-=', '*=', '/=',
    '%=', '**=', '&&=', '||=', '??=', '&=', '|=', '^=', '<<=', '>>=', '>>>=',
    'instanceof', 'in',
})
_NON_NULL_FOLLOW = frozenset({
    '.', '?.', '[', '(', ',', ';', ')', ']', '}', ':', '?', 'as', 'satisfies',
    'in', 'instanceof', *(_VALUE_BINOPS),
})


@dataclass
class _Tok:
    kind: str  # 'ws' | 'nl' | 'comment' | 'str' | 'tmpl' | 'tmpl_head' | 'tmpl_mid' | 'tmpl_tail' | 'regex' | 'word' | 'num' | 'punct'
    text: str


def _tokenize(src: str) -> list[_Tok]:
    tokens: list[_Tok] = []
    n = len(src)
    i = 0
    tmpl_stack: list[int] = []
    last_sig: _Tok | None = None

    def emit(kind: str, text: str) -> None:
        nonlocal last_sig
        tok = _Tok(kind, text)
        tokens.append(tok)
        if kind not in ('ws', 'nl', 'comment'):
            last_sig = tok

    def read_template(start_idx: int, is_head: bool) -> int:
        buf = [src[start_idx]]
        j = start_idx + 1
        while j < n:
            ch = src[j]
            if ch == '\\' and j + 1 < n:
                buf.append(src[j : j + 2])
                j += 2
                continue
            if ch == '$' and j + 1 < n and src[j + 1] == '{':
                buf.append('${')
                kind = 'tmpl_head' if is_head else 'tmpl_mid'
                emit(kind, ''.join(buf))
                tmpl_stack.append(1)
                return j + 2
            if ch == '`':
                buf.append('`')
                kind = 'tmpl' if is_head else 'tmpl_tail'
                emit(kind, ''.join(buf))
                return j + 1
            buf.append(ch)
            j += 1
        kind = 'tmpl' if is_head else 'tmpl_tail'
        emit(kind, ''.join(buf))
        return j

    while i < n:
        ch = src[i]
        if ch == '\r':
            if i + 1 < n and src[i + 1] == '\n':
                tokens.append(_Tok('nl', '\r\n'))
                i += 2
            else:
                tokens.append(_Tok('nl', '\n'))
                i += 1
            continue
        if ch == '\n':
            tokens.append(_Tok('nl', '\n'))
            i += 1
            continue
        if ch in (' ', '\t', '\v', '\f', '\ufeff'):
            j = i + 1
            while j < n and src[j] in (' ', '\t', '\v', '\f'):
                j += 1
            tokens.append(_Tok('ws', src[i:j]))
            i = j
            continue

        # Comments
        if ch == '/' and i + 1 < n and src[i + 1] == '/':
            j = i + 2
            while j < n and src[j] not in ('\n', '\r'):
                j += 1
            tokens.append(_Tok('comment', src[i:j]))
            i = j
            continue
        if ch == '/' and i + 1 < n and src[i + 1] == '*':
            j = src.find('*/', i + 2)
            j = n if j == -1 else j + 2
            tokens.append(_Tok('comment', src[i:j]))
            i = j
            continue

        # Strings
        if ch in ("'", '"'):
            quote = ch
            j = i + 1
            while j < n:
                c = src[j]
                if c == '\\' and j + 1 < n:
                    j += 2
                    continue
                if c == quote or c in ('\n', '\r'):
                    if c == quote:
                        j += 1
                    break
                j += 1
            emit('str', src[i:j])
            i = j
            continue

        # Template literals
        if ch == '`':
            i = read_template(i, is_head=True)
            continue

        # Regex literal vs division
        if ch == '/':
            can_regex = (
                last_sig is None
                or last_sig.kind == 'tmpl_head'
                or last_sig.kind == 'tmpl_mid'
                or (last_sig.kind == 'punct' and last_sig.text not in _REGEX_PREV_NO_PUNCT)
                or (last_sig.kind == 'word' and last_sig.text in _REGEX_PREV_WORDS)
            )
            if can_regex:
                j = i + 1
                in_class = False
                closed = False
                while j < n:
                    c = src[j]
                    if c == '\\' and j + 1 < n:
                        j += 2
                        continue
                    if c in ('\n', '\r'):
                        break
                    if c == '[':
                        in_class = True
                    elif c == ']' and in_class:
                        in_class = False
                    elif c == '/' and not in_class:
                        closed = True
                        j += 1
                        break
                    j += 1
                if closed:
                    while j < n and src[j].isalpha():
                        j += 1
                    emit('regex', src[i:j])
                    i = j
                    continue

        # Braces interacting with template interpolations
        if ch == '{':
            if tmpl_stack:
                tmpl_stack[-1] += 1
            emit('punct', '{')
            i += 1
            continue
        if ch == '}':
            if tmpl_stack:
                tmpl_stack[-1] -= 1
                if tmpl_stack[-1] == 0:
                    tmpl_stack.pop()
                    i = read_template(i, is_head=False)
                    continue
            emit('punct', '}')
            i += 1
            continue

        # Identifiers
        if ch.isalpha() or ch in ('_', '$'):
            m = _IDENT_RE.match(src, i)
            assert m is not None
            emit('word', m.group(0))
            i = m.end()
            continue

        # Numbers
        if ch.isdigit() or (ch == '.' and i + 1 < n and src[i + 1].isdigit()):
            m = _NUM_RE.match(src, i)
            if m:
                emit('num', m.group(0))
                i = m.end()
                continue

        # Optional chaining `?.` only when NOT ternary `a?.1:.2`
        if ch == '?' and i + 1 < n and src[i + 1] == '.' and not (i + 2 < n and src[i + 2].isdigit()):
            emit('punct', '?.')
            i += 2
            continue

        # Multi-character punctuators
        matched_multi = None
        for op in _MULTI_PUNCT:
            if op != '?.' and src.startswith(op, i):
                matched_multi = op
                break
        if matched_multi:
            emit('punct', matched_multi)
            i += len(matched_multi)
            continue

        emit('punct', ch)
        i += 1

    return tokens


class _TSRewriter:
    def __init__(self, tokens: list[_Tok]) -> None:
        self.tokens = tokens
        self.n = len(tokens)
        self.keep = [True] * self.n
        self.replace: dict[int, str] = {}
        self.insert_before: dict[int, list[str]] = {}

    def _is_trivia(self, idx: int) -> bool:
        return self.tokens[idx].kind in ('ws', 'nl', 'comment')

    def next_sig(self, idx: int, *, respect_keep: bool = False) -> int | None:
        j = idx
        while j < self.n:
            if not self._is_trivia(j) and (not respect_keep or self.keep[j]):
                return j
            j += 1
        return None

    def prev_sig(self, idx: int, *, respect_keep: bool = False) -> int | None:
        j = idx - 1
        while j >= 0:
            if not self._is_trivia(j) and (not respect_keep or self.keep[j]):
                return j
            j -= 1
        return None

    def next_non_ws(self, idx: int) -> int | None:
        j = idx
        while j < self.n:
            if self.tokens[j].kind not in ('ws', 'comment'):
                return j
            j += 1
        return None

    def has_newline_between(self, a: int, b: int) -> bool:
        for k in range(a + 1, b):
            if self.tokens[k].kind == 'nl':
                return True
        return False

    def drop_range(self, start: int, end: int) -> None:
        """Drop tokens [start, end) while preserving newline tokens for ASI safety."""
        for k in range(start, end):
            if self.tokens[k].kind != 'nl':
                self.keep[k] = False

    def match_delim(self, open_idx: int) -> int | None:
        open_ch = self.tokens[open_idx].text
        close_ch = {'(': ')', '[': ']', '{': '}'}[open_ch]
        depth = 0
        j = open_idx
        while j < self.n:
            if not self._is_trivia(j):
                t = self.tokens[j].text
                if t == open_ch:
                    depth += 1
                elif t == close_ch:
                    depth -= 1
                    if depth == 0:
                        return j
            j += 1
        return None

    def match_angle_type(self, open_idx: int) -> int | None:
        """Match `<...>` type argument / parameter list if syntactically valid as TS type."""
        depth = 0
        paren_depth = 0
        brace_depth = 0
        bracket_depth = 0
        j = open_idx
        while j < self.n:
            if not self._is_trivia(j):
                tok = self.tokens[j]
                t = tok.text
                if tok.kind == 'punct':
                    if t == ';' and paren_depth == 0 and brace_depth == 0:
                        return None
                    if t in ('&&', '||', '==', '!=', '===', '!==', '+=', '-=', '*=', '/='):
                        return None
                    if t == '(':
                        paren_depth += 1
                    elif t == ')':
                        paren_depth -= 1
                    elif t == '{':
                        brace_depth += 1
                    elif t == '}':
                        brace_depth -= 1
                    elif t == '[':
                        bracket_depth += 1
                    elif t == ']':
                        bracket_depth -= 1
                    elif paren_depth == 0 and brace_depth == 0 and bracket_depth == 0:
                        if t == '<':
                            depth += 1
                        elif t == '>':
                            depth -= 1
                            if depth == 0:
                                return j
                        elif t == '>>':
                            depth -= 2
                            if depth <= 0:
                                return None if depth < 0 else j
                        elif t == '>>>':
                            depth -= 3
                            if depth <= 0:
                                return None if depth < 0 else j
                        elif t in ('<=', '>=', '='):
                            return None
            j += 1
        return None

    def is_stmt_start(self, idx: int) -> bool:
        prev = self.prev_sig(idx)
        if prev is None:
            return True
        pt = self.tokens[prev].text
        if pt in (';', '{', '}'):
            return True
        if pt in ('export', 'default', 'declare'):
            return True
        return self.has_newline_between(prev, idx) and pt not in (
            '.', '?.', ',', '(', '[', '+', '-', '*', '/', '=', ':', '?', '&&', '||', '??',
        )

    def consume_type_expr(self, start_idx: int, *, stop_words: frozenset[str] = frozenset(), stop_punct: frozenset[str] = frozenset(), stop_on_newline: bool = True) -> int:
        """Return index right after a TS type expression starting at start_idx."""
        j = start_idx
        p_d = b_d = s_d = a_d = 0
        last_kept = start_idx - 1
        while j < self.n:
            tok = self.tokens[j]
            if tok.kind in ('ws', 'comment'):
                j += 1
                continue
            if tok.kind == 'nl':
                if stop_on_newline and p_d == 0 and b_d == 0 and s_d == 0 and a_d == 0:
                    nxt = self.next_sig(j + 1)
                    prev_text = self.tokens[last_kept].text if last_kept >= start_idx else ''
                    nxt_text = self.tokens[nxt].text if nxt is not None else ''
                    # Only continue across newline if operator explicitly joins lines.
                    if prev_text in ('|', '&', '=>', '<', ',', '.', '?', ':', '=', 'extends', 'infer', 'keyof', 'typeof', 'readonly'):
                        j += 1
                        continue
                    if nxt_text in ('|', '&'):
                        j += 1
                        continue
                    return j
                j += 1
                continue

            t = tok.text
            if p_d == 0 and b_d == 0 and s_d == 0 and a_d == 0:
                if t == '{' and '{' in stop_punct and (
                    last_kept < start_idx
                    or self.tokens[last_kept].text in ('|', '&', '=>', '(', '[', '<', ',', '?', ':')
                    or (
                        self.tokens[last_kept].kind == 'word'
                        and self.tokens[last_kept].text in ('extends', 'readonly', 'keyof', 'typeof', 'infer')
                    )
                ):
                    b_d += 1
                    last_kept = j
                    j += 1
                    continue
                if t in stop_punct or (tok.kind == 'word' and t in stop_words):
                    return j
                if tok.kind == 'word' and t == 'is' and last_kept >= start_idx:
                    j += 1
                    continue
                if t in (';', ')', ']', '}', ',', '=') and not (t == '=>' ):
                    return j
                if t == '?' and last_kept >= start_idx:
                    # Could be ternary `? trueBranch : falseBranch` or conditional type `T extends U ? X : Y`
                    # If previous token was NOT `extends` context, stop if followed by ternary outside extends.
                    if 'extends' not in {self.tokens[k].text for k in range(start_idx, j)}:
                        return j
                if t in _VALUE_BINOPS and t not in ('|', '&', '<', '>', '-'):
                    return j

            if tok.kind == 'punct':
                if t == '(':
                    p_d += 1
                elif t == ')':
                    if p_d == 0:
                        return j
                    p_d -= 1
                elif t == '{':
                    b_d += 1
                elif t == '}':
                    if b_d == 0:
                        return j
                    b_d -= 1
                elif t == '[':
                    s_d += 1
                elif t == ']':
                    if s_d == 0:
                        return j
                    s_d -= 1
                elif t == '<':
                    a_d += 1
                elif t == '>' and a_d > 0:
                    a_d -= 1
                elif t == '>>' and a_d > 0:
                    a_d = max(0, a_d - 2)
                elif t == '>>>' and a_d > 0:
                    a_d = max(0, a_d - 3)
            last_kept = j
            j += 1
        return j

    def rewrite(self) -> str:
        self._strip_top_and_type_decls()
        self._strip_classes()
        self._strip_expressions_and_annotations()
        out: list[str] = []
        for idx, tok in enumerate(self.tokens):
            if idx in self.insert_before:
                out.extend(self.insert_before[idx])
            if not self.keep[idx]:
                continue
            out.append(self.replace.get(idx, tok.text))
        return ''.join(out)

    def _strip_top_and_type_decls(self) -> None:
        i = 0
        while i < self.n:
            idx = self.next_sig(i, respect_keep=True)
            if idx is None:
                break
            tok = self.tokens[idx]
            if tok.kind != 'word':
                i = idx + 1
                continue
            w = tok.text

            # Strip `export type ...`, `export interface ...`, or standalone `export` / `export default`
            if w == 'export' and self.is_stmt_start(idx):
                nxt = self.next_sig(idx + 1)
                if nxt is not None and self.tokens[nxt].text in ('type', 'interface', 'abstract', 'const', 'let', 'var', 'function', 'async', 'class', 'enum', 'declare'):
                    self.keep[idx] = False
                    if self.tokens[nxt].text == 'type':
                        after_type = self.next_sig(nxt + 1)
                        if after_type is not None and self.tokens[after_type].text in ('{', '*'):
                            # export type { ... } [from '...']
                            j = nxt + 1
                            while j < self.n and self.tokens[j].text != ';':
                                if self.tokens[j].kind == 'nl':
                                    break
                                j += 1
                            if j < self.n and self.tokens[j].text == ';':
                                j += 1
                            self.drop_range(idx, j)
                            i = j
                            continue
                    i = nxt
                    continue
                if nxt is not None and self.tokens[nxt].text == 'default':
                    nxt2 = self.next_sig(nxt + 1)
                    if nxt2 is not None and self.tokens[nxt2].text in ('class', 'abstract', 'function', 'async', 'interface', 'type'):
                        self.drop_range(idx, nxt + 1)
                        i = nxt2
                        continue

            # Strip `import type ...`
            if w == 'import' and self.is_stmt_start(idx):
                nxt = self.next_sig(idx + 1)
                if nxt is not None and self.tokens[nxt].text == 'type':
                    j = nxt + 1
                    while j < self.n:
                        if self.tokens[j].text == ';':
                            j += 1
                            break
                        if self.tokens[j].kind == 'nl':
                            break
                        j += 1
                    self.drop_range(idx, j)
                    i = j
                    continue

            # Strip `declare ...`
            if w == 'declare' and self.is_stmt_start(idx):
                nxt = self.next_sig(idx + 1)
                if nxt is None:
                    self.keep[idx] = False
                    break
                nw = self.tokens[nxt].text
                if nw in ('namespace', 'module', 'global', 'interface'):
                    j = nxt + 1
                    while j < self.n and self.tokens[j].text != '{':
                        j += 1
                    if j < self.n:
                        end = self.match_delim(j)
                        end_idx = (end + 1) if end is not None else self.n
                        self.drop_range(idx, end_idx)
                        i = end_idx
                        continue
                if nw in ('abstract', 'class', 'enum'):
                    j = nxt + 1
                    while j < self.n and self.tokens[j].text != '{':
                        j += 1
                    if j < self.n:
                        end = self.match_delim(j)
                        end_idx = (end + 1) if end is not None else self.n
                        self.drop_range(idx, end_idx)
                        i = end_idx
                        continue
                if nw == 'type':
                    j = nxt + 1
                    while j < self.n and self.tokens[j].text != '=':
                        j += 1
                    if j < self.n:
                        end_idx = self.consume_type_expr(j + 1)
                        if end_idx < self.n and self.tokens[end_idx].text == ';':
                            end_idx += 1
                        self.drop_range(idx, end_idx)
                        i = end_idx
                        continue
                if nw in ('const', 'let', 'var', 'function'):
                    j = nxt + 1
                    # Scan up to `:`, `;`, or newline while skipping parameter/generic lists
                    while j < self.n:
                        t = self.tokens[j].text
                        if t in ('(', '[', '{'):
                            end_d = self.match_delim(j)
                            j = (end_d + 1) if end_d is not None else j + 1
                            continue
                        if t == '<':
                            end_a = self.match_angle_type(j)
                            if end_a is not None:
                                j = end_a + 1
                                continue
                        if t == ':':
                            end_idx = self.consume_type_expr(j + 1)
                            if end_idx < self.n and self.tokens[end_idx].text == ';':
                                end_idx += 1
                            self.drop_range(idx, end_idx)
                            j = end_idx
                            break
                        if t == ';':
                            self.drop_range(idx, j + 1)
                            j += 1
                            break
                        if self.tokens[j].kind == 'nl':
                            self.drop_range(idx, j)
                            break
                        j += 1
                    i = j
                    continue

            # Strip `interface Name ... { ... }`
            if w == 'interface' and self.is_stmt_start(idx):
                j = idx + 1
                while j < self.n and self.tokens[j].text != '{':
                    j += 1
                if j < self.n:
                    end = self.match_delim(j)
                    end_idx = (end + 1) if end is not None else self.n
                    self.drop_range(idx, end_idx)
                    i = end_idx
                    continue

            # Strip `type Name<T> = TypeExpr`
            if w == 'type' and self.is_stmt_start(idx):
                name_idx = self.next_sig(idx + 1)
                if name_idx is not None and self.tokens[name_idx].kind == 'word':
                    after = self.next_sig(name_idx + 1)
                    if after is not None and self.tokens[after].text == '<':
                        end_ang = self.match_angle_type(after)
                        if end_ang is not None:
                            after = self.next_sig(end_ang + 1)
                    if after is not None and self.tokens[after].text == '=':
                        end_idx = self.consume_type_expr(after + 1)
                        if end_idx < self.n and self.tokens[end_idx].text == ';':
                            end_idx += 1
                        self.drop_range(idx, end_idx)
                        i = end_idx
                        continue

            # Convert `enum` / `const enum` -> `const Name = { ... };`
            if w == 'enum' and self.is_stmt_start(idx):
                name_idx = self.next_sig(idx + 1)
                if name_idx is not None and self.tokens[name_idx].kind == 'word':
                    open_b = self.next_sig(name_idx + 1)
                    if open_b is not None and self.tokens[open_b].text == '{':
                        close_b = self.match_delim(open_b)
                        if close_b is not None:
                            prev = self.prev_sig(idx, respect_keep=True)
                            if prev is not None and self.tokens[prev].text == 'const':
                                self.keep[prev] = False
                            self.replace[idx] = 'const'
                            self.insert_before.setdefault(open_b, []).append('= ')
                            self._rewrite_enum_body(open_b, close_b)
                            i = close_b + 1
                            continue

            i = idx + 1

    def _rewrite_enum_body(self, open_b: int, close_b: int) -> None:
        j = open_b + 1
        auto_val = 0
        while j < close_b:
            k = self.next_sig(j)
            if k is None or k >= close_b:
                break
            if self.tokens[k].kind in ('word', 'str'):
                after = self.next_sig(k + 1)
                if after is not None and after < close_b and self.tokens[after].text == '=':
                    self.replace[after] = ':'
                    # Scan up to `,` or `}`
                    m = after + 1
                    depth = 0
                    val_tokens = []
                    while m < close_b:
                        t = self.tokens[m].text
                        if t in ('(', '[', '{'):
                            depth += 1
                        elif t in (')', ']', '}'):
                            depth -= 1
                        elif depth == 0 and t == ',':
                            break
                        if not self._is_trivia(m):
                            val_tokens.append(self.tokens[m])
                        m += 1
                    if len(val_tokens) == 1 and val_tokens[0].kind == 'num':
                        try:
                            auto_val = int(val_tokens[0].text, 0) + 1
                        except ValueError:
                            pass
                    j = m + 1
                    continue
                else:
                    self.insert_before.setdefault(k + 1, []).append(f': {auto_val}')
                    auto_val += 1
            j = k + 1

    def _strip_classes(self) -> None:
        i = 0
        while i < self.n:
            idx = self.next_sig(i, respect_keep=True)
            if idx is None:
                break
            tok = self.tokens[idx]
            if tok.kind == 'word' and tok.text == 'abstract':
                nxt = self.next_sig(idx + 1, respect_keep=True)
                if nxt is not None and self.tokens[nxt].text == 'class':
                    self.keep[idx] = False
                    idx = nxt
                    tok = self.tokens[idx]
            if tok.kind == 'word' and tok.text == 'class':
                prev = self.prev_sig(idx, respect_keep=True)
                if prev is None or self.tokens[prev].text not in ('.', '?.'):
                    end_class = self._rewrite_class(idx)
                    if end_class is not None:
                        # Continue INSIDE class too (skip only header)
                        pass
            i = idx + 1

    def _rewrite_class(self, class_idx: int) -> int | None:
        # Rewrite header from `class` until `{`
        j = class_idx + 1
        while j < self.n:
            if not self.keep[j] or self._is_trivia(j):
                j += 1
                continue
            t = self.tokens[j].text
            if t == '{':
                break
            if t == '<':
                end_ang = self.match_angle_type(j)
                if end_ang is not None:
                    self.drop_range(j, end_ang + 1)
                    j = end_ang + 1
                    continue
            if self.tokens[j].kind == 'word' and t == 'implements':
                k = j + 1
                while k < self.n and self.tokens[k].text != '{':
                    k += 1
                self.drop_range(j, k)
                j = k
                break
            j += 1
        if j >= self.n or self.tokens[j].text != '{':
            return None
        close_b = self.match_delim(j)
        if close_b is None:
            return None

        # Walk top-level members inside class `{ ... }`
        k = j + 1
        while k < close_b:
            m = self.next_sig(k, respect_keep=True)
            if m is None or m >= close_b:
                break
            if self.tokens[m].text == ';':
                k = m + 1
                continue

            # Strip member modifiers (`private`, `public`, `protected`, `readonly`, `override`, `abstract`, `declare`)
            member_start = m
            is_abstract_member = False
            while m < close_b:
                tok = self.tokens[m]
                if tok.kind == 'word' and tok.text in (*_ACCESS_MODIFIERS, 'abstract', 'declare'):
                    nxt = self.next_sig(m + 1, respect_keep=True)
                    if nxt is not None and nxt < close_b and (
                        self.tokens[nxt].kind == 'word'
                        or self.tokens[nxt].text in ('[', '*', '#', 'get', 'set')
                    ):
                        if tok.text == 'abstract':
                            is_abstract_member = True
                        self.keep[m] = False
                        m = nxt
                        continue
                break

            if m >= close_b:
                break

            # Allow `static` / `async` / `get` / `set` before another modifier (`static private x`)
            while m < close_b and self.tokens[m].kind == 'word' and self.tokens[m].text in ('static', 'async', 'get', 'set'):
                nxt = self.next_sig(m + 1, respect_keep=True)
                if nxt is not None and nxt < close_b and (self.tokens[nxt].kind == 'word' or self.tokens[nxt].text in ('[', '*')):
                    m = nxt
                    # Strip modifier right after static/async too
                    while m < close_b and self.tokens[m].kind == 'word' and self.tokens[m].text in (*_ACCESS_MODIFIERS, 'abstract'):
                        nxt2 = self.next_sig(m + 1, respect_keep=True)
                        if nxt2 is not None and nxt2 < close_b and (self.tokens[nxt2].kind == 'word' or self.tokens[nxt2].text in ('[', '*', 'get', 'set')):
                            if self.tokens[m].text == 'abstract':
                                is_abstract_member = True
                            self.keep[m] = False
                            m = nxt2
                            continue
                        break
                    continue
                break

            if m >= close_b:
                break

            # Read member name or computed property `[expr]`
            name_tok = self.tokens[m]
            if name_tok.text == '*':
                m = self.next_sig(m + 1, respect_keep=True) or m
                name_tok = self.tokens[m]
            is_constructor = name_tok.kind == 'word' and name_tok.text == 'constructor'
            after_name = None
            if name_tok.text == '[':
                end_sq = self.match_delim(m)
                after_name = self.next_sig((end_sq + 1) if end_sq is not None else m + 1, respect_keep=True)
            else:
                after_name = self.next_sig(m + 1, respect_keep=True)

            if after_name is None or after_name >= close_b:
                break

            # Strip optional generic `<T>` on method
            if self.tokens[after_name].text == '<':
                end_ang = self.match_angle_type(after_name)
                if end_ang is not None:
                    self.drop_range(after_name, end_ang + 1)
                    after_name = self.next_sig(end_ang + 1, respect_keep=True) or after_name

            if after_name >= close_b:
                break

            # Method: `name(...) [: Ret] { ... }` (or abstract/overload signature ending without `{`)
            if self.tokens[after_name].text == '(':
                close_p = self.match_delim(after_name)
                if close_p is None:
                    break
                param_props = self._rewrite_param_list(after_name, close_p, collect_prop_names=is_constructor)
                after_p = self.next_sig(close_p + 1, respect_keep=True)
                if after_p is not None and after_p < close_b and self.tokens[after_p].text == ':':
                    end_ret = self.consume_type_expr(after_p + 1, stop_punct=frozenset({'{', ';'}))
                    self.drop_range(after_p, end_ret)
                    after_p = self.next_sig(end_ret, respect_keep=True)
                if after_p is not None and after_p < close_b and self.tokens[after_p].text == '{':
                    body_end = self.match_delim(after_p)
                    if body_end is not None:
                        if param_props:
                            self._inject_constructor_props(after_p, body_end, param_props)
                        # Note: nested classes inside methods get visited by outer loop if needed.
                        k = body_end + 1
                        continue
                else:
                    # Abstract method or TS overload signature without `{}`
                    stmt_end = after_p if after_p is not None and after_p < close_b else close_b
                    if stmt_end < close_b and self.tokens[stmt_end].text == ';':
                        stmt_end += 1
                    self.drop_range(member_start, stmt_end)
                    k = stmt_end
                    continue

            # Field: `name[?!][: Type][= expr][;]`
            if self.tokens[after_name].text in ('?', '!'):
                self.keep[after_name] = False
                after_name = self.next_sig(after_name + 1, respect_keep=True) or after_name
            if after_name < close_b and self.tokens[after_name].text == ':':
                end_t = self.consume_type_expr(after_name + 1, stop_punct=frozenset({'=', ';'}))
                self.drop_range(after_name, end_t)
                after_name = self.next_sig(end_t, respect_keep=True) or end_t
            if is_abstract_member:
                end_m = after_name
                while end_m < close_b and self.tokens[end_m].text != ';' and self.tokens[end_m].kind != 'nl':
                    end_m += 1
                if end_m < close_b and self.tokens[end_m].text == ';':
                    end_m += 1
                self.drop_range(member_start, end_m)
                k = end_m
                continue
            # Advance past initializer expression until `;` or newline at depth 0
            cur = after_name
            p_d = b_d = s_d = 0
            while cur < close_b:
                tok = self.tokens[cur]
                if p_d == 0 and b_d == 0 and s_d == 0:
                    if tok.text == ';':
                        cur += 1
                        break
                    if tok.kind == 'nl':
                        prev = self.prev_sig(cur, respect_keep=True)
                        nxt = self.next_sig(cur + 1, respect_keep=True)
                        if prev is not None and self.tokens[prev].text not in ('=', '+', '-', '*', '/', ',', '(', '[', '{', '.', '?.', '&&', '||', '??', ':', '?') and (nxt is None or self.tokens[nxt].text not in ('.', '?.', '+', '-', '*', '/', '&&', '||', '??', '?', ':')):
                            break
                if tok.text == '(':
                    p_d += 1
                elif tok.text == ')':
                    p_d = max(0, p_d - 1)
                elif tok.text == '[':
                    s_d += 1
                elif tok.text == ']':
                    s_d = max(0, s_d - 1)
                elif tok.text == '{':
                    b_d += 1
                elif tok.text == '}':
                    b_d = max(0, b_d - 1)
                cur += 1
            k = cur
        return close_b

    def _inject_constructor_props(self, open_b: int, close_b: int, props: list[str]) -> None:
        assign = ' '.join(f'this.{p} = {p};' for p in props)
        first = self.next_sig(open_b + 1, respect_keep=True)
        if first is not None and first < close_b and self.tokens[first].text == 'super':
            p_open = self.next_sig(first + 1, respect_keep=True)
            if p_open is not None and self.tokens[p_open].text == '(':
                p_close = self.match_delim(p_open)
                if p_close is not None and p_close < close_b:
                    after_s = self.next_sig(p_close + 1, respect_keep=True)
                    if after_s is not None and self.tokens[after_s].text == ';':
                        self.insert_before.setdefault(after_s + 1, []).append(' ' + assign)
                    else:
                        self.insert_before.setdefault(p_close + 1, []).append('; ' + assign)
                    return
        self.insert_before.setdefault(open_b + 1, []).append(' ' + assign)

    def _rewrite_param_list(self, open_p: int, close_p: int, *, collect_prop_names: bool = False) -> list[str]:
        props: list[str] = []
        j = open_p + 1
        while j < close_p:
            p = self.next_sig(j, respect_keep=True)
            if p is None or p >= close_p:
                break
            if self.tokens[p].text == ',':
                j = p + 1
                continue
            param_start = p
            # Parameter modifiers in constructors (`private x: number`)
            has_prop_mod = False
            while p < close_p and self.tokens[p].kind == 'word' and self.tokens[p].text in _ACCESS_MODIFIERS:
                nxt = self.next_sig(p + 1, respect_keep=True)
                if nxt is not None and nxt < close_p and (self.tokens[nxt].kind == 'word' or self.tokens[nxt].text in ('{', '[')):
                    has_prop_mod = True
                    self.keep[p] = False
                    p = nxt
                    continue
                break
            if p >= close_p:
                break
            # `this: Type` parameter must be removed completely
            if self.tokens[p].kind == 'word' and self.tokens[p].text == 'this':
                nxt = self.next_sig(p + 1, respect_keep=True)
                if nxt is not None and nxt < close_p and self.tokens[nxt].text == ':':
                    end_t = self.consume_type_expr(nxt + 1, stop_punct=frozenset({',', ')'}), stop_on_newline=False)
                    if end_t < close_p and self.tokens[end_t].text == ',':
                        end_t += 1
                    self.drop_range(param_start, min(end_t, close_p))
                    j = min(end_t, close_p)
                    continue

            if self.tokens[p].text == '...':
                p = self.next_sig(p + 1, respect_keep=True) or p
            if self.tokens[p].text in ('{', '['):
                end_pat = self.match_delim(p)
                after_pat = self.next_sig((end_pat + 1) if end_pat is not None else p + 1, respect_keep=True)
            elif self.tokens[p].kind == 'word':
                if has_prop_mod and collect_prop_names:
                    props.append(self.tokens[p].text)
                after_pat = self.next_sig(p + 1, respect_keep=True)
            else:
                after_pat = self.next_sig(p + 1, respect_keep=True)

            if after_pat is not None and after_pat < close_p:
                if self.tokens[after_pat].text == '?':
                    self.keep[after_pat] = False
                    after_pat = self.next_sig(after_pat + 1, respect_keep=True) or after_pat
                if after_pat < close_p and self.tokens[after_pat].text == ':':
                    end_t = self.consume_type_expr(after_pat + 1, stop_punct=frozenset({'=', ',', ')'}), stop_on_newline=False)
                    self.drop_range(after_pat, min(end_t, close_p))
                    after_pat = min(end_t, close_p)

            # Skip past parameter default value to `,` or `close_p`
            cur = after_pat if after_pat is not None else p + 1
            p_d = b_d = s_d = 0
            while cur < close_p:
                t = self.tokens[cur].text
                if p_d == 0 and b_d == 0 and s_d == 0 and t == ',':
                    cur += 1
                    break
                if t == '(':
                    p_d += 1
                elif t == ')':
                    p_d = max(0, p_d - 1)
                elif t == '[':
                    s_d += 1
                elif t == ']':
                    s_d = max(0, s_d - 1)
                elif t == '{':
                    b_d += 1
                elif t == '}':
                    b_d = max(0, b_d - 1)
                cur += 1
            j = cur
        return props

    def _strip_expressions_and_annotations(self) -> None:
        ternary_depth = 0
        # Track paren stack to restore ternary_depth cleanly across grouping/calls
        i = 0
        while i < self.n:
            idx = self.next_sig(i, respect_keep=True)
            if idx is None:
                break
            tok = self.tokens[idx]
            w = tok.text

            if tok.kind == 'punct':
                if w == '?':
                    nxt = self.next_sig(idx + 1, respect_keep=True)
                    # Exclude `?:` optional marker only if inside types (already stripped) -> runtime `?` is ternary.
                    ternary_depth += 1
                    i = idx + 1
                    continue
                if w == ':' and ternary_depth > 0:
                    ternary_depth -= 1
                    i = idx + 1
                    continue

                # `!` postfix non-null assertion
                if w == '!':
                    prev = self.prev_sig(idx, respect_keep=True)
                    nxt = self.next_sig(idx + 1, respect_keep=True)
                    if prev is not None and self.tokens[prev].kind in ('word', 'str', 'regex', 'num', 'tmpl', 'tmpl_tail') or (prev is not None and self.tokens[prev].text in (')', ']', '}')):
                        if not self.has_newline_between(prev, idx):
                            if nxt is None or self.has_newline_between(idx, nxt) or self.tokens[nxt].text in _NON_NULL_FOLLOW or self.tokens[nxt].text == '?.':
                                # Do not confuse `!x` prefix negation after keywords (`return !x`, `if (!x)`)
                                if self.tokens[prev].kind == 'word' and self.tokens[prev].text in ('return', 'throw', 'case', 'else', 'await', 'yield', 'void', 'typeof', 'delete', 'in', 'of', 'instanceof'):
                                    pass
                                else:
                                    self.keep[idx] = False
                                    i = idx + 1
                                    continue

                # Generic type arguments on calls/new expressions or generic function/arrow `<T>(...)`
                if w == '<':
                    prev = self.prev_sig(idx, respect_keep=True)
                    if prev is not None and (
                        self.tokens[prev].kind == 'word'
                        or self.tokens[prev].text in (')', ']')
                        or self.tokens[prev].text in ('(', '=', ',', ':', 'return', '=>', '{', '[')
                    ):
                        end_ang = self.match_angle_type(idx)
                        if end_ang is not None:
                            after_ang = self.next_sig(end_ang + 1, respect_keep=True)
                            if after_ang is not None and self.tokens[after_ang].kind in ('tmpl', 'tmpl_head'):
                                self.drop_range(idx, end_ang + 1)
                                i = end_ang + 1
                                continue
                            if after_ang is not None and self.tokens[after_ang].text == '(':
                                # Disambiguate `(a < b) && c > (d)` vs `fn<T>(...)` / `<T>(x: T) => ...`
                                close_p = self.match_delim(after_ang)
                                is_call = prev is not None and (
                                    (self.tokens[prev].kind == 'word' and self.tokens[prev].text not in _REGEX_PREV_WORDS)
                                    or self.tokens[prev].text in (')', ']')
                                )
                                is_arrow = False
                                if close_p is not None:
                                    after_p = self.next_sig(close_p + 1, respect_keep=True)
                                    if after_p is not None and (self.tokens[after_p].text == '=>' or (self.tokens[after_p].text == ':' and ternary_depth == 0)):
                                        is_arrow = True
                                if is_call or is_arrow:
                                    self.drop_range(idx, end_ang + 1)
                                    i = end_ang + 1
                                    continue

                # Arrow function or paren function parameters: `(...) [: Ret] =>`
                if w == '(':
                    close_p = self.match_delim(idx)
                    if close_p is not None:
                        after_p = self.next_sig(close_p + 1, respect_keep=True)
                        is_fn_like = False
                        if after_p is not None:
                            if self.tokens[after_p].text == '=>':
                                is_fn_like = True
                            elif self.tokens[after_p].text == ':' and ternary_depth == 0:
                                end_ret = self.consume_type_expr(after_p + 1, stop_punct=frozenset({'=>', '{'}), stop_on_newline=False)
                                nxt_after = self.next_sig(end_ret, respect_keep=True)
                                if nxt_after is not None and self.tokens[nxt_after].text == '=>':
                                    is_fn_like = True
                                    self.drop_range(after_p, end_ret)
                                elif nxt_after is not None and self.tokens[nxt_after].text == '{':
                                    # Object method shorthand `{ foo(a: string): void { ... } }` or `function`
                                    prev = self.prev_sig(idx, respect_keep=True)
                                    if prev is not None and self.tokens[prev].kind in ('word', 'str') and self.tokens[prev].text not in ('if', 'for', 'while', 'switch', 'with', 'catch', 'return', 'typeof', 'void', 'delete', 'await', 'yield', 'throw', 'new'):
                                        is_fn_like = True
                                        self.drop_range(after_p, end_ret)
                        if is_fn_like:
                            self._rewrite_param_list(idx, close_p)
                        else:
                            # `catch (e: unknown)`
                            prev = self.prev_sig(idx, respect_keep=True)
                            if prev is not None and self.tokens[prev].text == 'catch':
                                self._rewrite_param_list(idx, close_p)

                i = idx + 1
                continue

            # `const` / `let` / `var` type annotations (`var x: T = ...` or `const { a: b }: T = ...`)
            if tok.kind == 'word' and w in ('const', 'let', 'var'):
                prev = self.prev_sig(idx, respect_keep=True)
                if prev is None or self.tokens[prev].text not in ('.', '?.'):
                    cur = idx + 1
                    while cur < self.n:
                        pat = self.next_sig(cur, respect_keep=True)
                        if pat is None:
                            break
                        if self.tokens[pat].text in ('{', '['):
                            end_pat = self.match_delim(pat)
                            after_pat = self.next_sig((end_pat + 1) if end_pat is not None else pat + 1, respect_keep=True)
                        elif self.tokens[pat].kind == 'word':
                            after_pat = self.next_sig(pat + 1, respect_keep=True)
                        else:
                            break
                        if after_pat is None:
                            break
                        if self.tokens[after_pat].text == ':':
                            end_t = self.consume_type_expr(after_pat + 1, stop_words=frozenset({'in', 'of'}), stop_punct=frozenset({'=', ',', ';'}))
                            self.drop_range(after_pat, end_t)
                            after_pat = self.next_sig(end_t, respect_keep=True)
                        if after_pat is None or self.tokens[after_pat].text != ',':
                            break
                        cur = after_pat + 1
                    i = idx + 1
                    continue

            # `function [name]<T>(params)[: Ret] {`
            if tok.kind == 'word' and w == 'function':
                prev = self.prev_sig(idx, respect_keep=True)
                if prev is None or self.tokens[prev].text not in ('.', '?.'):
                    p = self.next_sig(idx + 1, respect_keep=True)
                    if p is not None and self.tokens[p].text == '*':
                        p = self.next_sig(p + 1, respect_keep=True)
                    if p is not None and self.tokens[p].kind == 'word':
                        p = self.next_sig(p + 1, respect_keep=True)
                    if p is not None and self.tokens[p].text == '<':
                        end_ang = self.match_angle_type(p)
                        if end_ang is not None:
                            self.drop_range(p, end_ang + 1)
                            p = self.next_sig(end_ang + 1, respect_keep=True)
                    if p is not None and self.tokens[p].text == '(':
                        close_p = self.match_delim(p)
                        if close_p is not None:
                            self._rewrite_param_list(p, close_p)
                            after_p = self.next_sig(close_p + 1, respect_keep=True)
                            if after_p is not None and self.tokens[after_p].text == ':':
                                end_ret = self.consume_type_expr(after_p + 1, stop_punct=frozenset({'{', ';'}))
                                self.drop_range(after_p, end_ret)
                                if end_ret < self.n and self.tokens[end_ret].text != '{':
                                    # Ambient / overload signature `function foo(x: string): void;`
                                    end_sig = end_ret + 1 if end_ret < self.n and self.tokens[end_ret].text == ';' else end_ret
                                    self.drop_range(idx, end_sig)
                            i = idx + 1
                            continue

            # `expr as Type` / `expr satisfies Type`
            if tok.kind == 'word' and w in ('as', 'satisfies'):
                prev = self.prev_sig(idx, respect_keep=True)
                nxt = self.next_sig(idx + 1, respect_keep=True)
                if (
                    prev is not None
                    and nxt is not None
                    and self.tokens[prev].text not in ('.', '?.', ':', '{', ',', '(', '[', 'import', 'export', '*', 'const', 'let', 'var')
                    and not (self.tokens[nxt].text in (':', '=', ',', ')', '}', ';', '.', '?.'))
                    and not self.has_newline_between(prev, idx)
                ):
                    end_t = self.consume_type_expr(
                        idx + 1,
                        stop_punct=frozenset({':'}) if ternary_depth > 0 else frozenset(),
                    )
                    self.drop_range(idx, end_t)
                    i = end_t
                    continue

            i = idx + 1


def transpile_typescript(source: str) -> str:
    """Strip TypeScript syntax into clean ES2022 JavaScript without external Node tools."""
    if not isinstance(source, str):
        return ''
    cleaned = re.sub(r'^\s*///\s*<reference\b[^>]*/>\s*$', '', source, flags=re.MULTILINE)
    tokens = _tokenize(cleaned)
    rewriter = _TSRewriter(tokens)
    return rewriter.rewrite()


def prepare_extension_source(source: str, language: str = 'javascript') -> str:
    """Prepare JavaScript or TypeScript Seanime extension code for execution."""
    lang = (language or 'javascript').strip().lower()
    if lang == 'typescript':
        return transpile_typescript(source)
    if lang == 'javascript':
        cleaned = re.sub(r'^\s*///\s*<reference\b[^>]*/>\s*$', '', source or '', flags=re.MULTILINE)
        cleaned = re.sub(r'^\s*export\s+(?:default\s+)?(?=(?:class|function|async\s+function|const|let|var)\b)', '', cleaned, flags=re.MULTILINE)
        return cleaned
    raise ValueError(f"Langage d'extension Seanime non exécutable : {language}")
