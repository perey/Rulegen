#!/usr/bin/env python3

r"""Parse generation rules in a custom metalanguage.

The metalanguage used to specify generation rules is similar to BNF (and
ABNF), but uses different, more regex-inspired syntax. It also omits any
form of recursion or indefinite repetition, to keep output bounded.

Nonterminals are enclosed in angle brackets (U+003C and U+003E). The
initial nonterminal is always called <RESULT>. Terminals come in two
types, literals and database lookups. Literals are enclosed in double
quotation marks (U+0022). Database lookups are enclosed in square
brackets (U+005B and U+005D).

Production rules consist of a nonterminal, an equals sign (U+003D), and
a replacement expression, separated by optional whitespace. A rule is
terminated by a newline. (Note that newline handling is done by Python,
not by the parser.)

Selection between two alternative replacements is indicated by the pipe
or vertical line character (U+007C). An optional token is preceded (not
followed!) by a question mark (U+003F).

Comments begin with a hash character (U+0023) and continue to the end
of the line.

Rules files must be UTF-8 text. Identifiers in nonterminals and database
lookup terminals, and strings in literal terminals, contain arbitrary
text. Backslash escaping is used to escape closing characters, newline
characters (\n), and the backslash itself.

"""
# Copyright © 2015 Timothy Pederick.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

# Standard library imports.
from collections import defaultdict
from copy import copy

# Local imports.
from toposort import toposort, CyclicGraphError

# Root of generation rules.
INITIAL = 'RESULT'

# Parser states.
(AWAITING_NONTERMINAL, AWAITING_EQUALS, AWAITING_START_OF_RULE,
 CONTINUING_RULE, JUST_HAD_OPTION, INSIDE_NONTERMINAL,
 INSIDE_LITERAL, INSIDE_DBLOOKUP, ESCAPING_SOMETHING) = range(9)

NEXT_STATE = {AWAITING_NONTERMINAL: AWAITING_EQUALS,
              AWAITING_START_OF_RULE: CONTINUING_RULE,
              JUST_HAD_OPTION: CONTINUING_RULE}

# Parser output tokens.
class Token:
    """A token in a production rule."""
    token_type = None
    def __init__(self, content):
        self.content = content

    def __repr__(self):
        return '{}({!r})'.format(self.__class__.__name__, self.content)


class Nonterminal(Token):
    """A nonterminal in a production rule."""
    token_type = 'nonterminal'
    def __str__(self):
        return '<{}>'.format(self.content)


class Terminal(Token):
    """A terminal in a production rule."""
    token_type = 'terminal'


class Literal(Terminal):
    """A string literal in a production rule."""
    @property
    def escaped_content(self):
        # Escape double-quote characters.
        return self.content.replace('"', '\\"')

    def __str__(self):
        return '"{}"'.format(self.escaped_content)

    def escape_brackets(self):
        """Escape square brackets in the string literal.

        This makes it possible to mix (unquoted) string literals and
        database lookups in the same string, as the all_terminals()
        function does.

        """
        return self.content.translate(str.maketrans({'[': '\\[',
                                                     ']': '\\]'}))


class DBLookup(Terminal):
    """A database lookup in a production rule."""
    def __str__(self):
        return '[{}]'.format(self.content)


class Control(Token):
    """A control token in a production rule."""
    token_type = 'control'
    def __str__(self):
        return self.content


# Syntax characters.
NONTERMINAL_START, NONTERMINAL_END = '<>'
LITERAL_START = LITERAL_END = '"'
DBLOOKUP_START, DBLOOKUP_END = '[]'
DEFINITION_START = '='
ESCAPE_START = '\\'
SELECTION = '|'
OPTION = '?'
COMMENT_START = '#'
END_CHAR = {INSIDE_NONTERMINAL: NONTERMINAL_END,
            INSIDE_LITERAL: LITERAL_END,
            INSIDE_DBLOOKUP: DBLOOKUP_END}
TOKEN_CLASS = {INSIDE_NONTERMINAL: Nonterminal,
               INSIDE_LITERAL: Literal,
               INSIDE_DBLOOKUP: DBLookup}

# Errors for parsing rules.
class RuleParserError(Exception):
    """Base class for all errors in the ruleparser module."""
    pass


class RuleError(RuleParserError):
    """One or more rules violate the expected semantics."""
    pass


class ParseError(RuleParserError):
    """Could not parse the rule given."""
    def __init__(self, got, expected=None):
        message = ('got unexpected {}'.format(got) if expected is None else
                   'got {}, expected {}'.format(got, expected))
        super().__init__(message)


def parse_rule(rule):
    """Parse a single rule."""
    tokens = []

    state = AWAITING_NONTERMINAL
    state_stack = []
    content = []

    for char in rule:
        # Ignore whitespace outside of terminals, nonterminals, and escapes.
        if (state not in (INSIDE_NONTERMINAL, INSIDE_LITERAL, INSIDE_DBLOOKUP,
                          ESCAPING_SOMETHING) and char.isspace()):
            continue

        # When waiting for the initial nonterminal, we accept a nonterminal
        # (duh) or a comment (which ends the rule before it starts).
        if state == AWAITING_NONTERMINAL:
            if char == NONTERMINAL_START:
                state_stack.append(state)
                state = INSIDE_NONTERMINAL
            elif char == COMMENT_START:
                break
            else:
                raise ParseError(repr(char), 'a nonterminal')

        # When waiting for the equals sign that separates a nonterminal from
        # its expansion, that's the only thing we accept.
        elif state == AWAITING_EQUALS:
            if char == DEFINITION_START:
                tokens.append(Control(char))
                state_stack = []
                state = AWAITING_START_OF_RULE
            else:
                raise ParseError(repr(char), 'a rule definition')

        # When waiting for the start of a rule, we accept any terminal or
        # nonterminal, or an option character. An option character must be
        # followed by any terminal or nonterminal, but not an option character.
        elif state in (AWAITING_START_OF_RULE, JUST_HAD_OPTION):
            if char == NONTERMINAL_START:
                state_stack.append(state)
                state = INSIDE_NONTERMINAL
            elif char == LITERAL_START:
                state_stack.append(state)
                state = INSIDE_LITERAL
            elif char == DBLOOKUP_START:
                state_stack.append(state)
                state = INSIDE_DBLOOKUP
            elif char == OPTION and state != JUST_HAD_OPTION:
                tokens.append(Control(char))
                state_stack = []
                state = JUST_HAD_OPTION
            else:
                raise ParseError(repr(char), 'a terminal or nonterminal')

        # When we've had at least one terminal or nonterminal in a rule, we
        # can accept another terminal or nonterminal, a control character, or a
        # comment (which ends the rule).
        elif state == CONTINUING_RULE:
            if char == NONTERMINAL_START:
                state_stack.append(state)
                state = INSIDE_NONTERMINAL
            elif char == LITERAL_START:
                state_stack.append(state)
                state = INSIDE_LITERAL
            elif char == DBLOOKUP_START:
                state_stack.append(state)
                state = INSIDE_DBLOOKUP
            elif char == SELECTION:
                tokens.append(Control(char))
                state_stack = []
                state = AWAITING_START_OF_RULE
            elif char == OPTION:
                tokens.append(Control(char))
                state_stack = []
                state = JUST_HAD_OPTION
            elif char == COMMENT_START:
                break
            else:
                raise ParseError(repr(char))

        # When we're inside a terminal or nonterminal, we accept anything.
        elif state in (INSIDE_NONTERMINAL, INSIDE_LITERAL, INSIDE_DBLOOKUP):
            if char == ESCAPE_START:
                state_stack.append(state)
                state = ESCAPING_SOMETHING
            elif char == END_CHAR[state]:
                tokens.append(TOKEN_CLASS[state](''.join(content)))
                content = []
                state = state_stack.pop()

                state = NEXT_STATE.get(state, state)
            else:
                content.append(char)

        # When we're escaping a character, we accept anything.
        elif state == ESCAPING_SOMETHING:
            # Newlines are not allowed in string literals, even escaped, so
            # '\n' is not handled specially; it just escapes the letter 'n'.
            content.append(char)
            state = state_stack.pop()

        else:
            raise ParseError('state')

    # Were we expecting the end of the rule?
    if state not in (AWAITING_NONTERMINAL, CONTINUING_RULE, JUST_HAD_OPTION):
        raise ParseError('EOL')

    return tokens


def parse_rules(rulefile):
    """Parse a file of rules.

    Keyword arguments:
        rulefile -- The filename of the file of rules.

    """
    # Read and parse the rules.
    rules = {}
    with open(rulefile, encoding='utf-8') as rf:
        for line in rf:
            parsed_rule = parse_rule(line)
            if len(parsed_rule) > 0:
                # Unpack the nonterminal, the equals sign, and the rest of the
                # rule (the actual production).
                nonterminal, equals, *production = parsed_rule

                if (not isinstance(nonterminal, Nonterminal) or
                    not (isinstance(equals, Control) and
                         equals.content == '=')):
                    # Wait, what?
                    raise RuleError('parsed rule is nonconformant')

                if nonterminal.content in rules:
                    raise RuleError('attempted redefinition of '
                                    '{!r}'.format(nonterminal.content))
                else:
                    rules[nonterminal.content] = production
            # Else there were no tokens (e.g. a blank line or comment).

    # Check that all nonterminals have definitions ending in terminals, and
    # that the initial nonterminal, <RESULT>, exists.
    dependencies = defaultdict(list)
    seen_nonterminals = set()
    unseen_nonterminals = {INITIAL}
    while len(unseen_nonterminals) > 0:
        next_nonterminal = unseen_nonterminals.pop()
        seen_nonterminals.add(next_nonterminal)

        production = rules.get(next_nonterminal)
        if production is None:
            raise RuleError('nonterminal {!r} is '
                            'undefined'.format(next_nonterminal))

        for token in production:
            if isinstance(token, Nonterminal):
                unseen_nonterminals.add(token.content)
                dependencies[next_nonterminal].append(token.content)

    # Are all nonterminal definitions reachable from <RESULT>?
    if len(seen_nonterminals) < len(rules):
        raise RuleError('{} nonterminals are '
                        'unreachable'.format(len(rules) -
                                             len(seen_nonterminals)))
    # Sanity check.
    elif len(seen_nonterminals) > len(rules):
        raise RuleError('expected {} nonterminals, somehow got '
                        '{}'.format(len(rules), len(seen_nonterminals)))

    # Check for recursion in the production rules.
    try:
        toposort(dependencies, startnodes={INITIAL})
    except CyclicGraphError as cge:
        raise RuleError('recursive rule definition exists') from cge
    return rules


class Tree:
    """A stupidly simple n-ary tree."""
    def __init__(self, content, parent=None):
        self.content = content
        self.parent = parent
        self.children = []

    def expand(self, rules):
        """Expand this (sub-)tree, if possible."""
        expanded = False

        if isinstance(self.content, Nonterminal):
            # Expand nonterminals to their results.
            expanded = True
            self.children = [Tree(token, self)
                                for token in rules[self.content.content]]
        elif isinstance(self.content, Control):
            # All control tokens cause expansion and require the position of
            # this node within its parent's children.
            expanded = True
            node_pos = self.parent.children.index(self)

            if self.content.content == OPTION:
                # Expand options to two nodes, one with and one without the
                # next sibling (the optional token).
                optional_token = self.parent.children.pop(node_pos + 1)
                first_child = (optional_token if isinstance(optional_token,
                                                            Tree) else
                               Tree(optional_token))
                first_child.parent = self
                self.children = [first_child, Tree(None, self)]
            else:
                assert self.content.content == SELECTION
                # Expand selections to two nodes, one with all prior siblings
                # and one with all following siblings.
                prior = self.parent.children[:node_pos]
                following = self.parent.children[node_pos + 1:]
                left, right = Tree(True, self), Tree(False, self)
                left.children, right.children = prior, following
                # Reparent all those transplanted children.
                for side in left, right:
                    for child in side.children:
                        child.parent = side
                self.parent.children = [self]
                self.children = [left, right]

        return expanded


def all_terminals(rules):
    r"""Generate all possible terminal sequences from a parsed ruleset.

    Each result is a string containing only terminal tokens (string
    literals and database lookups). As database lookups are enclosed in
    square brackets, any square brackets that appear in string literals
    are escaped.
        >>> test_rules = {INITIAL: [Nonterminal('A'), Literal(' '),
        ...                         Nonterminal('B')],
        ...               'A': [Literal('Hello'), Control(SELECTION),
        ...                     Literal('Goodbye')],
        ...               'B': [Control(OPTION), Literal('[cruel] '),
        ...                     Literal('world')]}
        >>> for terminal in all_terminals(test_rules):
        ...     print(terminal)
        Hello \[cruel\] world
        Hello world
        Goodbye \[cruel\] world
        Goodbye world

    """
    # Store terminal sequences in a set, so that duplicates (sequences which
    # can be arrived at through more than one production) are weeded out.
    terminal_seqs = set()
    ruletree = Tree(Nonterminal(INITIAL))

    all_leaves_are_terminals = False

    while not all_leaves_are_terminals:
        # Assume we're going to break out on this iteration.
        all_leaves_are_terminals = True

        # Traverse the tree breadth-first, expanding each node as we go.
        nodes = [ruletree]
        while len(nodes) > 0:
            next_node = nodes.pop(0)
            # If it's not a leaf node, expand it.
            if len(next_node.children) == 0:
                all_leaves_are_terminals = (all_leaves_are_terminals and
                                            not next_node.expand(rules))
            # Traverse over its children.
            nodes.extend(next_node.children)

    # Traverse the tree depth-first, yielding terminal sequences this time.
    stack = [([], [ruletree])]
    while len(stack) > 0:
        current, nodes = stack.pop()

        while len(nodes) > 0:
            next_node = nodes.pop()
            # For terminals, add them to this sequence.
            if isinstance(next_node.content, Terminal):
                assert len(next_node.children) == 0
                if next_node.content is not None:
                    current.append(next_node.content.escape_brackets()
                                   if isinstance(next_node.content,
                                                 Literal) else
                                   str(next_node.content))
            # For control tokens, save the state with one alternative. Output
            # a sequence with the other alternative. Then reload the state and
            # use the first alternative.
            elif isinstance(next_node.content, Control):
                copy_of_current, copy_of_nodes = copy(current), copy(nodes)

                option_a, option_b = next_node.children
                nodes.append(option_a)
                copy_of_nodes.append(option_b)

                stack.append((copy_of_current, copy_of_nodes))
            # For anything else, iterate over its children.
            else:
                nodes.extend(reversed(next_node.children))
        terminal_seq = ''.join(current)
        if terminal_seq not in terminal_seqs:
            terminal_seqs.add(terminal_seq)
            yield terminal_seq


def parse_terminals(s):
    r"""Parse a string for a sequence of terminals.

    The string output from all_terminals() is suitable for saving to a
    database. This function then turns it back into a sequence containing
    Literal and DBLookup tokens. Note that this is not guaranteed to
    reproduce the original tokens, as successive string literals will be
    collapsed into one.
        >>> parse_terminals('Hello, \[friend\] [Name]!')
        [Literal('Hello, [friend] '), DBLookup('Name'), Literal('!')]

    """
    tokens = []
    current_token = []
    state = INSIDE_LITERAL
    old_states = []
    for char in s:
        if state == ESCAPING_SOMETHING:
            current_token.append(char)
            state = old_states.pop()
        elif char == ESCAPE_START:
            old_states.append(state)
            state = ESCAPING_SOMETHING
        elif state == INSIDE_LITERAL:
            if char == DBLOOKUP_START:
                tokens.append(Literal(''.join(current_token)))
                current_token = []
                state = INSIDE_DBLOOKUP
            else:
                current_token.append(char)
        elif state == INSIDE_DBLOOKUP:
            if char == DBLOOKUP_END:
                tokens.append(DBLookup(''.join(current_token)))
                current_token = []
                state = INSIDE_LITERAL
            else:
                current_token.append(char)
    if state != INSIDE_LITERAL:
        raise ParseError('EOL')
    else:
        tokens.append(Literal(''.join(current_token)))
    return tokens


if __name__ == '__main__':
    import sys
    try:
        rules = parse_rules(sys.argv[1])
    except IndexError:
        print('Running doctests...')
        import doctest
        doctest.testmod()
    else:
        for n, terminal in enumerate(all_terminals(rules)):
            print(terminal)
        print(n + 1)
