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
# Standard library imports.
from collections import defaultdict
from copy import copy, deepcopy

# Topological sort algorithm, used to detect cycles.
class CyclicGraphError(Exception):
    pass


def unreachable_nodes(graph):
    """Find unreachable nodes in a directed graph."""
    candidates = set(graph.keys())
    for destinations in graph.values():
        for dest in destinations:
            candidates.discard(dest)
    return candidates


def toposort(graph, startnodes=None):
    """Perform topological sorting on a directed graph.

    The graph is to be represented as a mapping of nodes to lists of
    nodes, representing an arc from the key to each item in the list.
    This is the representation used in the essay "Python Patterns -
    Implementing Graphs" <https://www.python.org/doc/essays/graphs/>.

    The sort algorithm is from Kahn (1962).

    Keyword arguments:
        graph -- The graph to be sorted.
        startnodes -- A set of known nodes with no incoming edges. If
            omitted, the graph is searched for these as the first step
            of the algorithm; thus, providing this information can save
            time if it is already known.

    """
    sorted_elements = []
    editable_graph = deepcopy(graph)
    editable_nodes = (unreachable_nodes(graph) if startnodes is None else
                      deepcopy(startnodes))

    while len(editable_nodes) > 0:
        node = editable_nodes.pop()
        sorted_elements.append(node)

        destinations = editable_graph[node]
        editable_graph[node] = []
        unreachable_now = unreachable_nodes(editable_graph)
        for dest in destinations:
            if dest in unreachable_now:
                editable_nodes.add(dest)

    if any(len(destinations) > 0 for destinations in editable_graph.values()):
        raise CyclicGraphError('cannot sort graph: cycle exists')
    else:
        return sorted_elements


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
    def __str__(self):
        return '"{}"'.format(self.content)


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
            if char == 'n':
                content.append('\n')
            else:
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


def list_terminals(rules):
    r"""List all possible terminal sequences from a parsed ruleset.

        >>> test_rules = {INITIAL: [Nonterminal('A'), Literal(' '),
        ...                         Nonterminal('B')],
        ...               'A': [Literal('Hello'), Control(SELECTION),
        ...                     Literal('Goodbye')],
        ...               'B': [Control(OPTION), Literal('cruel '),
        ...                     Literal('world')]}
        >>> for terminal in list_terminals(test_rules):
        ...     print(terminal)
        Goodbye world
        Goodbye cruel world
        Hello cruel world
        Hello world

    """
    terminals = set()
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
                    current.append(next_node.content.content
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
        terminals.add(''.join(current))

    return terminals


if __name__ == '__main__':
    import sys
    try:
        rules = parse_rules(sys.argv[1])
    except IndexError:
        print('Running doctests...')
        import doctest
        doctest.testmod()
    else:
        for n, terminal in enumerate(list_terminals(rules)):
            print(terminal)
        print(n + 1)
