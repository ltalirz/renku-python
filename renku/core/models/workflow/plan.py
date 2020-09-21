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
"""Represent run templates."""

import pathlib
import urllib.parse
import uuid
from pathlib import Path

from marshmallow import EXCLUDE
from werkzeug.utils import secure_filename

from renku.core.models.calamus import JsonLDSchema, Nested, fields, prov, renku, schema
from renku.core.models.workflow.parameters import (
    CommandArgumentSchema,
    CommandInput,
    CommandInputTemplate,
    CommandInputTemplateSchema,
    CommandOutput,
    CommandOutputTemplate,
    CommandOutputTemplateSchema,
)
from renku.core.models.workflow.run import Run


class Plan:
    """Represent a `renku run` execution template."""

    def __init__(self, id_, arguments=None, command=None, inputs=None, name=None, outputs=None, success_codes=None):
        """Initialize."""
        self.arguments = arguments or []
        self.command = command
        self.id_ = id_
        self.inputs = inputs or []
        # TODO create a shorter name
        self.name = name or "{}-{}".format(secure_filename(self.command), uuid.uuid4().hex)
        self.outputs = outputs or []
        self.success_codes = success_codes or []


    @classmethod
    def from_jsonld(cls, data):
        """Create an instance from JSON-LD data."""
        if isinstance(data, cls):
            return data
        elif not isinstance(data, dict):
            raise ValueError(data)

        return PlanSchema(flattened=True).load(data)

    @classmethod
    def from_run(cls, run: Run, name):
        """Create a Plan from a Run."""
        assert not run.subprocesses, f"Cannot create from a Run with subprocesses: {run._id}"

        uuid_ = _extract_run_uuid(run._id)
        plan_id = cls.generate_id(uuid_=uuid_)

        inputs = [_convert_command_input(i, plan_id) for i in run.inputs]
        outputs = [_convert_command_output(o, plan_id) for o in run.outputs]

        return cls(
            arguments=run.arguments,
            command=run.command,
            id_=plan_id,
            inputs=inputs,
            name=name,
            outputs=outputs,
            success_codes=run.successcodes,
        )

    @staticmethod
    def generate_id(uuid_=None):
        """Generate an identifier for the plan."""
        uuid_ = uuid_ or str(uuid.uuid4())
        # TODO: use run's domain instead of localhost
        return urllib.parse.urljoin("https://localhost", pathlib.posixpath.join("plans", uuid_))

    def to_jsonld(self):
        """Create JSON-LD."""
        return PlanSchema(flattened=True).dump(self)

    def is_similar_to(self, other):
        def get_input_patterns(plan):
            return {e.consumes for e in plan.inputs}

        def get_output_patterns(plan):
            return {e.produces for e in plan.outputs}

        def get_arguments(plan):
            return {(a.position, a.prefix, a.value) for a in plan.arguments}

        return (
            self.command == other.command
            and set(self.success_codes) == set(other.success_codes)
            and get_input_patterns(self) == get_input_patterns(other)
            and get_output_patterns(self) == get_output_patterns(self)
            and get_arguments(self) == get_arguments(other)
        )


def _extract_run_uuid(run_id) -> str:
    # https://localhost/runs/723fd784-9347-4081-84de-a6dbb067545b
    parsed_url = urllib.parse.urlparse(run_id)
    return parsed_url.path[len("/runs/") :]


def _convert_command_input(input_: CommandInput, plan_id) -> CommandInputTemplate:
    """Convert a CommandInput to CommandInputTemplate."""
    assert isinstance(input_, CommandInput)

    # TODO: add a '**' if this is a directory
    # TODO: For now this is always a fully qualified path; in future this might be a glob pattern.
    consumes = input_.consumes.path

    return CommandInputTemplate(
        id=CommandInputTemplate.generate_id(plan_id=plan_id, id_=Path(input_._id).name),
        consumes=consumes,
        mapped_to=input_.mapped_to,
        position=input_.position,
        prefix=input_.prefix,
    )


def _convert_command_output(output: CommandOutput, plan_id) -> CommandOutputTemplate:
    """Convert a CommandOutput to CommandOutputTemplate."""
    assert isinstance(output, CommandOutput)

    # TODO: add a '*' if this is a directory
    # TODO: For now this is always a fully qualified path; in future this might be glob pattern.
    produces = output.produces.path

    return CommandOutputTemplate(
        id=CommandOutputTemplate.generate_id(plan_id=plan_id, id_=Path(output._id).name),
        produces=produces,
        mapped_to=output.mapped_to,
        position=output.position,
        prefix=output.prefix,
        create_folder=output.create_folder,
    )


class PlanSchema(JsonLDSchema):
    """Plan schema."""

    class Meta:
        """Meta class."""

        rdf_type = [prov.Plan]
        model = Plan
        unknown = EXCLUDE

    arguments = Nested(renku.hasArguments, CommandArgumentSchema, many=True, missing=None)
    command = fields.String(renku.command, missing=None)
    id_ = fields.Id()
    inputs = Nested(renku.hasInputs, CommandInputTemplateSchema, many=True, missing=None)
    name = fields.String(schema.name, missing=None)
    outputs = Nested(renku.hasOutputs, CommandOutputTemplateSchema, many=True, missing=None)
    success_codes = fields.List(renku.successCodes, fields.Integer(), missing=[0])
