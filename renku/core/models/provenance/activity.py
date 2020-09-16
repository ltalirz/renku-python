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
"""Represent a run."""
import json
import pathlib
import urllib
import uuid
from pathlib import Path

import attr
from git import GitCommandError
from marshmallow import EXCLUDE

from renku.core.models.calamus import JsonLDSchema, Nested, fields, prov, renku, schema
from renku.core.models.entities import Entity, EntitySchema
from renku.core.models.projects import Project, ProjectSchema
from renku.core.models.provenance.activities import ProcessRun
from renku.core.models.provenance.agents import PersonSchema, SoftwareAgentSchema
from renku.core.models.provenance.qualified import (
    Association,
    AssociationSchema,
    Generation,
    GenerationSchema,
    Usage,
    UsageSchema,
)
from renku.core.models.workflow.plan import Plan


@attr.s(eq=False, order=False)
class Activity:
    """Represent an activity in the repository."""

    _id = attr.ib(default=None, kw_only=True)
    _project = attr.ib(default=None, kw_only=True, type=Project)

    agents = attr.ib(kw_only=True)
    association = attr.ib(default=None, kw_only=True)
    ended_at_time = attr.ib(kw_only=True)
    generated = attr.ib(default=None, kw_only=True)
    invalidated = attr.ib(default=None, kw_only=True)
    order = attr.ib(default=None, kw_only=True, type=int)
    path = attr.ib(default=None, converter=lambda v: str(v) if v is not None else None, kw_only=True)
    qualified_usage = attr.ib(default=None, kw_only=True)
    started_at_time = attr.ib(kw_only=True)
    # TODO: _collections = attr.ib(default=attr.Factory(OrderedDict), init=False, kw_only=True)
    # TODO: _was_informed_by = attr.ib(kw_only=True,)
    # TODO: annotations = attr.ib(kw_only=True, default=None)
    # TODO: influenced = attr.ib(kw_only=True)

    @classmethod
    def from_process_run(cls, process_run: ProcessRun, path: Path, plan: Plan, client, order=None):
        """Create an Activity from a ProcessRun."""
        activity_id = Activity.generate_id()
        path = (client.path / path).relative_to(client.path).as_posix()

        association = Association(agent=process_run.association.agent, id=activity_id + "/association", plan=plan)

        generated = [_convert_generation(g, activity_id, client) for g in process_run.generated]
        qualified_usage = [_convert_usage(u, activity_id, client) for u in process_run.qualified_usage]
        invalidated = [_convert_entity(e, activity_id, client) for e in process_run.invalidated]

        return cls(
            agents=process_run.agents,
            association=association,
            ended_at_time=process_run.ended_at_time,
            generated=generated,
            id=activity_id,
            invalidated=invalidated,
            order=order,
            path=path,
            project=process_run._project,
            qualified_usage=qualified_usage,
            started_at_time=process_run.started_at_time,
        )

    @staticmethod
    def generate_id():
        """Generate an identifier for an activity."""
        # TODO: use proper domain instead of localhost
        return urllib.parse.urljoin("https://localhost", pathlib.posixpath.join("activities", str(uuid.uuid4())))

    @classmethod
    def from_jsonld(cls, data):
        """Create an instance from JSON-LD data."""
        if isinstance(data, cls):
            return data
        if not isinstance(data, list):
            raise ValueError(data)

        return ActivitySchema(flattened=True).load(data)

    def as_jsonld(self):
        """Create JSON-LD."""
        return ActivitySchema(flattened=True).dump(self)


def _convert_usage(usage: Usage, activity_id, client) -> Usage:
    """Convert a CommandInput to CommandInputTemplate."""
    assert isinstance(usage, Usage)

    entity = _convert_entity(entity=usage.entity, activity_id=activity_id, client=client)
    sanitized_id = _extract_sanitized_id(usage._id)
    return Usage(id=f"{activity_id}/{sanitized_id}", entity=entity, role=usage.role)


def _convert_generation(generation: Generation, activity_id, client) -> Generation:
    """Convert a CommandInput to CommandInputTemplate."""
    assert isinstance(generation, Generation)

    entity = _convert_entity(entity=generation.entity, activity_id=activity_id, client=client)
    sanitized_id = _extract_sanitized_id(generation._id)
    return Generation(id=f"{activity_id}/{sanitized_id}", entity=entity, role=generation.role)


def _convert_entity(entity: Entity, activity_id, client) -> Entity:
    """Convert a CommandInput to CommandInputTemplate."""
    assert isinstance(entity, Entity)

    checksum = _get_object_hash(entity=entity, client=client)
    id_ = _generate_entity_id(entity_checksum=checksum, path=entity.path, activity_id=activity_id)
    return Entity(id=id_, checksum=checksum, path=entity.path, project=entity._project)


def _extract_sanitized_id(qualified_id):
    parsed_url = urllib.parse.urlparse(qualified_id)
    # /activities/commit/de77cca5d831ac37670adf3e71e377000bf21b5c/inputs/1
    # /activities/commit/de77cca5d831ac37670adf3e71e377000bf21b5c/outputs/78dfe88241c44cb0ae094e60fe9cdd02
    path = parsed_url.path
    start = path.find("/inputs/") if "/inputs/" in path else path.find("/outputs/")

    if start < 0 or not path.startswith("/activities/commit"):
        raise ValueError(f"Invalid qualified identifier: {qualified_id}")

    return path[start + 1 :]


def _generate_entity_id(entity_checksum, path, activity_id):
    quoted_path = urllib.parse.quote(str(path))
    return urllib.parse.urljoin(activity_id, pathlib.posixpath.join("blob", f"{entity_checksum}", f"{quoted_path}"))


def _get_object_hash(entity: Entity, client):
    commit_sha = _extract_commit_sha(entity_id=entity._id)
    path = str(entity.path)
    try:
        return client.repo.git.rev_parse(f"{commit_sha}:{path}")
    except GitCommandError:
        # TODO: what if the project is broken
        # raise ValueError(f"Cannot get object hash '{commit_sha}:{path}'")
        return commit_sha


def _extract_commit_sha(entity_id: str):
    parsed_url = urllib.parse.urlparse(entity_id)
    # /blob/a3bf8a165dd56da078b96f2ca2ff22f14a3bdd57/input
    path = parsed_url.path

    if not path.startswith("/blob/"):
        raise ValueError(f"Invalid entity identifier: {entity_id}")

    return path[len("/blob/") :].split("/", 1)[0]


@attr.s(eq=False, order=False)
class ActivityCollection:

    members = attr.ib(factory=list, kw_only=True)

    @classmethod
    def from_json(cls, path):
        """Return an instance from a YAML file."""
        # TODO: we should not write inside a read
        with open(path) as file_:
            data = json.load(file_)
        return cls.from_jsonld(data=data)

    @classmethod
    def from_jsonld(cls, data):
        """Create an instance from JSON-LD data."""
        if isinstance(data, cls):
            return data
        elif not isinstance(data, list):
            raise ValueError(data)

        return ActivityCollectionSchema(flattened=True).load(data)

    def add(self, activity):
        self.members.append(activity)

    def as_jsonld(self):
        """Create JSON-LD."""
        return ActivityCollectionSchema(flattened=True).dump(self)

    def to_json(self, path):
        """Write an instance to YAML file."""
        data = self.as_jsonld()
        with open(path, "w", encoding="utf-8") as file_:
            json.dump(data, file_, ensure_ascii=False, sort_keys=True, indent=2)


class ActivitySchema(JsonLDSchema):
    """Activity schema."""

    class Meta:
        """Meta class."""

        rdf_type = prov.Activity
        model = Activity
        unknown = EXCLUDE

    _id = fields.Id(init_name="id")
    _project = Nested(schema.isPartOf, ProjectSchema, init_name="project", missing=None)
    agents = Nested(prov.wasAssociatedWith, [PersonSchema, SoftwareAgentSchema], many=True)
    association = Nested(prov.qualifiedAssociation, AssociationSchema)
    ended_at_time = fields.DateTime(prov.endedAtTime, add_value_types=True)
    generated = Nested(prov.activity, GenerationSchema, reverse=True, many=True, missing=None)
    invalidated = Nested(prov.wasInvalidatedBy, EntitySchema, reverse=True, many=True, missing=None)
    order = fields.Integer(renku.order)
    path = fields.String(prov.atLocation)
    qualified_usage = Nested(prov.qualifiedUsage, UsageSchema, many=True)
    started_at_time = fields.DateTime(prov.startedAtTime, add_value_types=True)

    # TODO: _was_informed_by = fields.List(prov.wasInformedBy, fields.IRI(), init_name="was_informed_by")
    # TODO: annotations = Nested(oa.hasTarget, AnnotationSchema, reverse=True, many=True)
    # TODO: influenced = Nested(prov.influenced, CollectionSchema, many=True)


class ActivityCollectionSchema(JsonLDSchema):
    """Activity schema."""

    class Meta:
        """Meta class."""

        rdf_type = schema.Collection
        model = ActivityCollection
        unknown = EXCLUDE

    members = Nested(prov.qualifiedUsage, ActivitySchema, many=True)
