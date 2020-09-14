# -*- coding: utf-8 -*-
#
# Copyright 2018-2020 - Swiss Data Science Center (SDSC)
# A partnership between École Polytechnique Fédérale de Lausanne (EPFL) and
# Eidgenössische Technische Hochschule Zürich (ETHZ).
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Represent dependency graph."""
from pathlib import Path

import attr
from marshmallow import EXCLUDE

from renku.core.models import jsonld
from renku.core.models.calamus import JsonLDSchema, Nested, schema
from renku.core.models.provenance.activity import Activity, ActivitySchema


@attr.s(eq=False, order=False)
class ProvenanceGraph:
    """A graph of all executions (Activities)."""

    # TODO: dependency graph can have cycles in it because up until now there was no check to prevent this

    __reference__ = attr.ib(default=None, init=False, type=str)
    _nodes = attr.ib(factory=list, kw_only=True)
    _order = attr.ib(default=None, init=False)

    def __attrs_post_init__(self):
        """Set uninitialized properties."""
        if self._nodes is None:
            self._nodes = []
        self._order = 1 if len(self._nodes) == 0 else max([n.order for n in self._nodes]) + 1

    @classmethod
    def from_jsonld(cls, data):
        """Create an instance from JSON-LD data."""
        if isinstance(data, cls):
            return data
        elif not isinstance(data, list):
            raise ValueError(data)

        return ProvenanceGraphSchema(flattened=True).load(data)

    @classmethod
    def from_yaml(cls, path):
        """Return an instance from a YAML file."""
        # TODO: we should not write inside a read
        if Path(path).exists():
            data = jsonld.read_yaml(path)
            self = cls.from_jsonld(data=data)
            self.__reference__ = path
        else:
            self = ProvenanceGraph(nodes=[])
            self.__reference__ = path
            self.to_yaml()

        return self

    @property
    def activities(self):
        """Return a map from order to activity."""
        return {n.order: n for n in self._nodes}

    def add(self, node: Activity):
        """Add a node to the graph."""
        node.order = self._order
        self._order += 1
        self._nodes.append(node)

    def as_jsonld(self):
        """Create JSON-LD."""
        return ProvenanceGraphSchema(flattened=True).dump(self)

    def to_yaml(self):
        """Write an instance to YAML file."""
        data = self.as_jsonld()
        jsonld.write_yaml(path=self.__reference__, data=data)

    def to_conjunctive_graph(self):
        """Create an RDFLib ConjunctiveGraph."""
        import json
        import pyld
        from rdflib import ConjunctiveGraph
        from rdflib.plugin import Parser, register

        output = pyld.jsonld.expand([action.as_jsonld() for action in self._nodes])
        data = json.dumps(output, indent=2)

        register("json-ld", Parser, "rdflib_jsonld.parser", "JsonLDParser")

        graph = ConjunctiveGraph().parse(data=data, format="json-ld")

        graph.bind("prov", "http://www.w3.org/ns/prov#")
        graph.bind("foaf", "http://xmlns.com/foaf/0.1/")
        graph.bind("wfdesc", "http://purl.org/wf4ever/wfdesc#")
        graph.bind("wf", "http://www.w3.org/2005/01/wf/flow#")
        graph.bind("wfprov", "http://purl.org/wf4ever/wfprov#")
        graph.bind("schema", "http://schema.org/")
        graph.bind("renku", "https://swissdatasciencecenter.github.io/renku-ontology#")

        return graph


class ProvenanceGraphSchema(JsonLDSchema):
    """ProvenanceGraph schema."""

    # TODO: use better property names for graph and nodes

    class Meta:
        """Meta class."""

        rdf_type = [schema.Collection]
        model = ProvenanceGraph
        unknown = EXCLUDE

    _nodes = Nested(schema.hasPart, ActivitySchema, init_name="nodes", many=True, missing=None)


ALL_USAGES = """
    SELECT ?path ?checksum ?order
    WHERE
    {
        ?activity a prov:Activity .
        ?activity renku:order ?order .
        ?activity (prov:qualifiedUsage/prov:entity) ?entity .
        ?entity renku:checksum ?checksum .
        ?entity prov:atLocation ?path .
    }
    """


LATEST_USAGES = """
    SELECT ?path ?checksum ?order ?maxOrder
    WHERE
    {
        {
            SELECT ?path ?checksum ?order
            WHERE
            {
                ?activity a prov:Activity .
                ?entity renku:checksum ?checksum .
                ?entity prov:atLocation ?path .
                ?entity (prov:qualifiedGeneration/prov:activity) ?activity .
                ?activity renku:order ?order
            }
        }
        .
        {
            SELECT ?path (MAX(?order_) AS ?maxOrder)
            WHERE
            {
                SELECT ?path ?order_
                WHERE
                {
                    ?activity a prov:Activity .
                    ?entity prov:atLocation ?path .
                    ?entity (prov:qualifiedGeneration/prov:activity) ?activity .
                    ?activity renku:order ?order_
                }
            }
            GROUP BY ?path
        }
        FILTER(?order = ?maxOrder)
    }
    """


LATEST_GENERATIONS = """
    SELECT ?path ?checksum ?order ?maxOrder
    WHERE
    {
        {
            SELECT ?path ?checksum ?order
            WHERE
            {
                ?entity a prov:Entity .
                ?entity renku:checksum ?checksum .
                ?entity prov:atLocation ?path .
                ?entity (prov:qualifiedGeneration/prov:activity) ?activity .
                ?activity renku:order ?order
            }
        }
        .
        {
            SELECT ?path (MAX(?order_) AS ?maxOrder)
            WHERE
            {
                SELECT ?path ?order_
                WHERE
                {
                    ?entity a prov:Entity .
                    ?entity prov:atLocation ?path .
                    ?entity (prov:qualifiedGeneration/prov:activity) ?activity .
                    ?activity renku:order ?order_
                }
            }
            GROUP BY ?path
        }
        FILTER(?order = ?maxOrder)
    }
    """
