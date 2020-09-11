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

import attr
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


@attr.s(eq=False, order=False)
class Plan:
    """Represent a `renku run` execution template."""

    _id = attr.ib(default=None, kw_only=True)
    arguments = attr.ib(factory=list, kw_only=True)
    command = attr.ib(default=None, kw_only=True, type=str)
    inputs = attr.ib(factory=list, kw_only=True)
    name = attr.ib(kw_only=True)
    outputs = attr.ib(factory=list, kw_only=True)
    success_codes = attr.ib(kw_only=True, factory=list, type=list)

    @classmethod
    def from_run(cls, run: Run, name):
        """Create a Plan from a Run."""
        if run.subprocesses:
            raise ValueError("Cannot create from a Run with subprocesses")

        uuid_ = _extract_run_uuid(run._id)
        plan_id = cls.generate_id(uuid_=uuid_)

        inputs = [_convert_command_input(i, plan_id) for i in run.inputs]
        outputs = [_convert_command_output(o, plan_id) for o in run.outputs]

        return cls(
            arguments=run.arguments,
            command=run.command,
            id=plan_id,
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

    def __attrs_post_init__(self):
        """Set uninitialized properties."""
        if not self._id:
            self._id = self.generate_id()

        if not self.name:
            # TODO create a shorter name in DG
            self.name = "{}-{}".format(secure_filename(self.command), uuid.uuid4().hex)

    @classmethod
    def from_jsonld(cls, data):
        """Create an instance from JSON-LD data."""
        if isinstance(data, cls):
            return data
        elif not isinstance(data, dict):
            raise ValueError(data)

        return PlanSchema(flattened=True).load(data)

    def as_jsonld(self):
        """Create JSON-LD."""
        return PlanSchema(flattened=True).dump(self)


def _extract_run_uuid(run_id) -> str:
    # https://localhost/runs/723fd784-9347-4081-84de-a6dbb067545b
    parsed_url = urllib.parse.urlparse(run_id)
    return parsed_url.path[len("/runs/") :]


def _convert_command_input(input_: CommandInput, plan_id) -> CommandInputTemplate:
    """Convert a CommandInput to CommandInputTemplate."""
    assert isinstance(input_, CommandInput)

    # TODO: add a '*' if this is a directory
    # TODO: For now this is always a fully qualified path; in future this might be glob pattern.
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

    _id = fields.Id(init_name="id")
    arguments = Nested(renku.hasArguments, CommandArgumentSchema, many=True, missing=None)
    command = fields.String(renku.command, missing=None)
    inputs = Nested(renku.hasInputs, CommandInputTemplateSchema, many=True, missing=None)
    name = fields.String(schema.name, missing=None)
    outputs = Nested(renku.hasOutputs, CommandOutputTemplateSchema, many=True, missing=None)
    success_codes = fields.List(renku.successCodes, fields.Integer(), missing=[0])
