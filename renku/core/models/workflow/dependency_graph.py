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
from renku.core.models.calamus import JsonLDSchema, Nested, renku, schema
from renku.core.models.workflow.plan import PlanSchema, Plan


@attr.s(eq=False, order=False)
class DependencyGraph:
    """A graph of all execution templates (Plans)."""

    # TODO: dependency graph can have cycles in it because up until now there was no check to prevent this

    _nodes = attr.ib(factory=list, kw_only=True)

    def __attrs_post_init__(self):
        """Set uninitialized properties."""
        if self._nodes is None:
            self._nodes = []

    @classmethod
    def from_jsonld(cls, data):
        """Create an instance from JSON-LD data."""
        if isinstance(data, cls):
            return data
        elif not isinstance(data, list):
            raise ValueError(data)

        return DependencyGraphSchema(flattened=True).load(data)

    @classmethod
    def from_yaml(cls, path):
        """Return an instance from a YAML file."""
        # TODO: we should not write inside a read
        if Path(path).exists():
            data = jsonld.read_yaml(path)
            self = cls.from_jsonld(data=data)
            self.__reference__ = path
        else:
            self = DependencyGraph(nodes=[])
            self.__reference__ = path
            self.to_yaml()

        return self

    def add_node(self, node: Plan):
        """Add a node to the graph."""
        # TODO: Check if a node with the same _id exists and do not add this one
        self._nodes.append(node)

    def as_jsonld(self):
        """Create JSON-LD."""
        return DependencyGraphSchema(flattened=True).dump(self)

    def to_yaml(self):
        """Write an instance to YAML file."""
        data = self.as_jsonld()
        jsonld.write_yaml(path=self.__reference__, data=data)


class DependencyGraphSchema(JsonLDSchema):
    """DependencyGraph schema."""

    # TODO: use better property names for graph and nodes

    class Meta:
        """Meta class."""

        rdf_type = [schema.Collection]
        model = DependencyGraph
        unknown = EXCLUDE

    _nodes = Nested(schema.hasPart, PlanSchema, init_name="nodes", many=True, missing=None)
