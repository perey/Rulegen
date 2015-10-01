#!/usr/bin/env python3

"""Topological sorting of directed graphs."""
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
from copy import deepcopy


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
