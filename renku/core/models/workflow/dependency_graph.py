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
import json
from pathlib import Path

from marshmallow import EXCLUDE

from renku.core.models.calamus import JsonLDSchema, Nested, schema
from renku.core.models.workflow.plan import Plan, PlanSchema


class DependencyGraph:
    """A graph of all execution templates (Plans)."""

    # TODO: dependency graph can have cycles in it because up until now there was no check to prevent this

    def __init__(self, nodes=None):
        """Set uninitialized properties."""
        self._nodes = nodes or []
        self._path = None  # TODO: Calamus complains if this is in parameters list

    def add(self, node: Plan):
        """Add a node to the graph."""
        # TODO: Check if a node with the same _id exists and do not add this one
        # TODO: Check if name is unique
        self._nodes.append(node)

    def find_similar_plan(self, node: Plan) -> Plan:
        """Search for a similar node and return it."""
        for n in self._nodes:
            if n.is_similar_to(node):
                return n

    @classmethod
    def from_json(cls, path):
        """Create an instance from a file."""
        if Path(path).exists():
            with open(path) as file_:
                data = json.load(file_)
                self = cls.from_jsonld(data=data)
        else:
            self = DependencyGraph(nodes=[])

        self._path = path

        return self

    @classmethod
    def from_jsonld(cls, data):
        """Create an instance from JSON-LD data."""
        if isinstance(data, cls):
            return data
        elif not isinstance(data, list):
            raise ValueError(data)

        return DependencyGraphSchema(flattened=True).load(data)

    def to_jsonld(self):
        """Create JSON-LD."""
        return DependencyGraphSchema(flattened=True).dump(self)

    def to_json(self, path=None):
        """Write to file."""
        path = path or self._path
        data = self.to_jsonld()
        with open(path, "w", encoding="utf-8") as file_:
            json.dump(data, file_, ensure_ascii=False, sort_keys=True, indent=2)


class DependencyGraphSchema(JsonLDSchema):
    """DependencyGraph schema."""

    # TODO: use better property names for graph and nodes

    class Meta:
        """Meta class."""

        rdf_type = [schema.Collection]
        model = DependencyGraph
        unknown = EXCLUDE

    _nodes = Nested(schema.hasPart, PlanSchema, init_name="nodes", many=True, missing=None)
