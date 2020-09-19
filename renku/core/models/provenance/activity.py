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
from typing import List

from git import GitCommandError
from marshmallow import EXCLUDE

from renku.core.models.calamus import JsonLDSchema, Nested, fields, prov, renku, schema
from renku.core.models.entities import Entity, EntitySchema, Collection
from renku.core.models.projects import ProjectSchema
from renku.core.models.provenance.activities import Activity as ActivityRun, ProcessRun, WorkflowRun
from renku.core.models.provenance.agents import PersonSchema, SoftwareAgentSchema
from renku.core.models.provenance.qualified import (
    Association,
    AssociationSchema,
    Generation,
    GenerationSchema,
    Usage,
    UsageSchema,
)
from renku.core.models.workflow.dependency_graph import DependencyGraph
from renku.core.models.workflow.plan import Plan


class Activity:
    """Represent an activity in the repository."""

    def __init__(
        self,
        agents=None,
        association=None,
        ended_at_time=None,
        generated=None,
        id_=None,
        invalidated=None,
        order=None,
        path=None,
        project=None,
        qualified_usage=None,
        started_at_time=None,
        # TODO: _collections = attr.ib(default=attr.Factory(OrderedDict), init=False, kw_only=True)
        # TODO: _was_informed_by = attr.ib(kw_only=True,)
        # TODO: annotations = attr.ib(kw_only=True, default=None)
        # TODO: influenced = attr.ib(kw_only=True)
    ):
        """Initialize."""
        self.agents = agents
        self.association = association
        self.ended_at_time = ended_at_time
        self.generated = generated
        self.id_ = id_
        self.invalidated = invalidated
        self.order = order
        self.path = str(path) if path else None
        self.project = project
        self.qualified_usage = qualified_usage
        self.started_at_time = started_at_time

    @classmethod
    def from_process_run(cls, process_run: ProcessRun, plan: Plan, client, path=None, order=None):
        """Create an Activity from a ProcessRun."""
        activity_id = Activity.generate_id()
        # if path:
        #     path = str((client.path / path).relative_to(client.path))

        association = Association(agent=process_run.association.agent, id=f"{activity_id}/association", plan=plan)

        # FIXME: The same entity can have the same id during different times in its lifetime (e.g. different commit_sha,
        # but the same content). When it gets flattened, some fields will have multiple values which will cause an error
        # during deserialization. This should be fixed in Calamus by creating different ids for such an entity. Also we
        # should store those information in the Generation object.
        all_entities = {}

        qualified_usage = []
        for q_usage in process_run.qualified_usage:
            usages = _convert_usage(q_usage, activity_id, client)
            for usage in usages:
                usage.entity = all_entities.setdefault(usage.entity._id, usage.entity)

                found = False
                for existing_usage in qualified_usage:
                    if existing_usage._id == usage._id:
                        assert existing_usage.role == usage.role
                        found = True
                        break

                if not found:
                    qualified_usage.append(usage)

        generated = [_convert_generation(g, activity_id, client) for g in process_run.generated]
        invalidated = [_convert_entity(e, activity_id, client) for e in process_run.invalidated]

        return cls(
            agents=process_run.agents,
            association=association,
            ended_at_time=process_run.ended_at_time,
            generated=generated,
            id_=activity_id,
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
        """Create an instance from JSON-LD."""
        if isinstance(data, cls):
            return data
        if not isinstance(data, list):
            raise ValueError(data)

        return ActivitySchema(flattened=True).load(data)

    def to_jsonld(self):
        """Create JSON-LD."""
        return ActivitySchema(flattened=True).dump(self)


def _convert_usage(usage: Usage, activity_id, client) -> List[Usage]:
    """Convert a CommandInput to CommandInputTemplate."""
    assert isinstance(usage, Usage)

    entities = _convert_usage_entity(entity=usage.entity, activity_id=activity_id, client=client)
    assert entities, f"Top level entity in usage was not found: {usage._id}"

    usages = []

    for entity in entities:
        quoted_path = urllib.parse.quote(entity.path)
        usage_id = urllib.parse.urljoin(activity_id, pathlib.posixpath.join("usage", entity.checksum, quoted_path))
        usages.append(Usage(id=usage_id, entity=entity, role=usage.role))

    return usages


def _convert_generation(generation: Generation, activity_id, client) -> List[Generation]:
    """Convert a CommandInput to CommandInputTemplate."""
    assert isinstance(generation, Generation)

    generations = []

    entities = _convert_generation_entity(entity=usage.entity, activity_id=activity_id, client=client)
    assert entities, f"Top level entity in usage was not found: {usage._id}"


    entity = _convert_entity(entity=generation.entity, activity_id=activity_id, client=client)
    sanitized_id = _extract_generation_sanitized_id(generation._id)
    return Generation(id=f"{activity_id}/{sanitized_id}", entity=entity, role=generation.role)


def _extract_usage_sanitized_id(usage_id):
    # /activities/commit/de77cca5d831ac37670adf3e71e377000bf21b5c/inputs/1
    path = urllib.parse.urlparse(usage_id).path
    start = path.find("/inputs/")
    assert path.startswith("/activities/commit") and start > 0, f"Invalid usage identifier: {usage_id}"

    return path[start + 1 :]


def _extract_generation_sanitized_id(generation_id):
    # /activities/commit/de77cca5d831ac37670adf3e71e377000bf21b5c/outputs/78dfe88241c44cb0ae094e60fe9cdd02
    path = urllib.parse.urlparse(generation_id).path
    start = path.find("/outputs/")
    assert path.startswith("/activities/commit") and start > 0, f"Invalid generation identifier: {generation_id}"

    return path[start + 1 :]


def _convert_usage_entity(entity: Entity, activity_id, client) -> List[Entity]:
    """Convert an Entity to one with proper metadata.

    For Collection return list of all sub-entities that existed in the same commit as Collection or before it.
    """
    assert isinstance(entity, Entity)

    commit_sha = _extract_commit_sha(entity_id=entity._id)
    checksum = _get_object_hash(commit_sha=commit_sha, path=entity.path, client=client)
    if not checksum:
        return []

    id_ = _generate_entity_id(entity_checksum=checksum, path=entity.path, activity_id=activity_id)
    new_entity = Entity(id=id_, checksum=checksum, path=entity.path, project=entity._project, commit_sha=commit_sha)
    assert type(new_entity) is type(entity)

    entities = [new_entity]

    if isinstance(entity, Collection):
        for sub_entity in entity.members:
            entities += _convert_usage_entity(entity=sub_entity, activity_id=activity_id, client=client)

    return entities


def _convert_generation_entity(entity: Entity, activity_id, client) -> List[Entity]:
    """Convert a CommandInput to CommandInputTemplate."""
    assert isinstance(entity, Entity)

    commit_sha = _extract_commit_sha(entity_id=entity._id)
    checksum = _get_object_hash(commit_sha=commit_sha, path=entity.path, client=client)
    if not checksum:
        return []

    id_ = _generate_entity_id(entity_checksum=checksum, path=entity.path, activity_id=activity_id)
    new_entity = Entity(id=id_, checksum=checksum, path=entity.path, project=entity._project, commit_sha=commit_sha)
    assert type(new_entity) is type(entity)

    entities = [new_entity]

    if isinstance(entity, Collection):
        for sub_entity in entity.members:
            entities += _convert_usage_entity(entity=sub_entity, activity_id=activity_id, client=client)

    return entities


def _generate_entity_id(entity_checksum, path, activity_id):
    quoted_path = urllib.parse.quote(path)
    path = pathlib.posixpath.join("blob", entity_checksum, quoted_path)

    return urllib.parse.urlparse(activity_id)._replace(path=path)


def _get_object_hash(commit_sha, path, client):
    path = str(path)
    try:
        return client.repo.git.rev_parse(f"{commit_sha}:{path}")
    except GitCommandError:
        # TODO: it also can be that the file was not there when the command ran but was there when workflows were
        # migrated.
        # this can happen for usage. can it also happen for generation?
        # TODO: what if the project is broken
        # raise ValueError(f"Cannot get object hash '{commit_sha}:{path}'")
        print(f"Cannot find object hash {commit_sha}/{path}")
        return None


def _extract_commit_sha(entity_id: str):
    # /blob/a3bf8a165dd56da078b96f2ca2ff22f14a3bdd57/input
    path = urllib.parse.urlparse(entity_id).path
    assert path.startswith("/blob/"), f"Invalid entity identifier: {entity_id}"

    return path[len("/blob/") :].split("/", 1)[0]


class ActivityCollection:
    """Equivalent of a workflow file."""

    def __init__(self, members=None, path=None):
        """Initialize."""
        self.members = members or []
        self.path = path

    @classmethod
    def from_activity_run(cls, activity_run: ActivityRun, dependency_graph: DependencyGraph, client, first_order: int):
        """Convert a ProcessRun/WorkflowRun to ActivityCollection."""

        def get_process_runs() -> list:
            assert isinstance(activity_run, WorkflowRun)
            # Use Plan subprocesses to get activities because it is guaranteed to have correct order
            activities = [s.process.activity for s in activity_run.association.plan.subprocesses]
            assert {a._id for a in activities} == {s._id for s in activity_run.subprocesses}
            return activities

        process_runs = get_process_runs() if isinstance(activity_run, WorkflowRun) else [activity_run]

        activity_collection = ActivityCollection()
        order = first_order

        for process_run in process_runs:
            assert isinstance(process_run, ProcessRun)
            run = process_run.association.plan
            if run.subprocesses:
                assert len(run.subprocesses) == 1, f"Run in ProcessRun has multiple steps: {run._id}"
                run = run.subprocesses[0]

            plan = Plan.from_run(run=run, name=None)
            plan = dependency_graph.find_similar_plan(plan) or plan
            dependency_graph.add(plan)

            # process_run = run.activity

            activity = Activity.from_process_run(process_run=process_run, plan=plan, client=client, order=order)
            order += 1
            activity_collection.add(activity)

    def add(self, activity):
        self.members.append(activity)

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

    def to_jsonld(self):
        """Create JSON-LD."""
        return ActivityCollectionSchema(flattened=True).dump(self)

    def to_json(self, path=None):
        """Write to file."""
        path = path or self.path

        for activity in self.members:
            activity.path = path

        data = self.to_jsonld()
        with open(path, "w", encoding="utf-8") as file_:
            json.dump(data, file_, ensure_ascii=False, sort_keys=True, indent=2)


class ActivitySchema(JsonLDSchema):
    """Activity schema."""

    class Meta:
        """Meta class."""

        rdf_type = prov.Activity
        model = Activity
        unknown = EXCLUDE

    agents = Nested(prov.wasAssociatedWith, [PersonSchema, SoftwareAgentSchema], many=True)
    association = Nested(prov.qualifiedAssociation, AssociationSchema)
    ended_at_time = fields.DateTime(prov.endedAtTime, add_value_types=True)
    generated = Nested(prov.activity, GenerationSchema, reverse=True, many=True, missing=None)
    id_ = fields.Id()
    invalidated = Nested(prov.wasInvalidatedBy, EntitySchema, reverse=True, many=True, missing=None)
    order = fields.Integer(renku.order)
    path = fields.String(prov.atLocation)
    project = Nested(schema.isPartOf, ProjectSchema, missing=None)
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
