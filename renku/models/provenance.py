# -*- coding: utf-8 -*-
#
# Copyright 2018 - Swiss Data Science Center (SDSC)
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
"""Graph builder."""

import os
from datetime import datetime

import attr
import yaml

from renku.api import LocalClient
from renku.models import _jsonld as jsonld
from renku.models._datastructures import DirectoryTree
from renku.models.cwl._ascwl import CWLClass


@jsonld.s(
    type='prov:Usage',
    context={
        'prov': 'http://www.w3.org/ns/prov#',
    },
)
class Dependency(object):
    """Represent a dependent path."""

    commit = attr.ib()
    client = attr.ib()

    path = jsonld.ib(context='prov:entity', default=None)
    id = jsonld.ib(context='prov:hadRole', default=None)

    submodules = attr.ib(default=attr.Factory(list))

    _id = jsonld.ib(context='@id', init=False)

    @_id.default
    def default_id(self):
        """Configure calculated ID."""
        return 'url:sha1:{self.commit.hexsha}#{self.path}'.format(self=self)

    @classmethod
    def from_revision(cls, client, path, revision='HEAD', **kwargs):
        """Return dependency from given path and revision."""
        return cls(
            client=client,
            commit=client.find_previous_commit(path, revision=revision),
            path=path,
            **kwargs
        )


@jsonld.s(
    type='prov:Activity',
    context={
        'prov': 'http://www.w3.org/ns/prov#',
        'rdfs': 'http://www.w3.org/2000/01/rdf-schema#',
    },
)
class Activity(object):
    """Represent an activity in the repository."""

    commit = attr.ib()
    client = attr.ib()

    process = attr.ib(default=None)
    process_path = jsonld.ib(context='prov:hadPlan', default=None)
    outputs = attr.ib()

    parent = attr.ib(default=None)

    submodules = attr.ib(default=attr.Factory(list))

    used = jsonld.ib(context='prov:used', default=None)

    generated = jsonld.ib(context='prov:generated', default=attr.Factory(list))
    started_at_time = jsonld.ib(
        context={
            '@id': 'prov:startedAtTime',
            '@type': 'http://www.w3.org/2001/XMLSchema#dateTime',
        },
    )

    ended_at_time = jsonld.ib(
        context={
            '@id': 'prov:endedAtTime',
            '@type': 'http://www.w3.org/2001/XMLSchema#dateTime',
        },
    )

    _id = jsonld.ib(context='@id', init=False)
    _label = jsonld.ib(context='rdfs:label', init=False)

    @property
    def paths(self):
        """Return all paths in the commit."""
        return set(self.commit.stats.files.keys())

    @_id.default
    def default_id(self):
        """Configure calculated ID."""
        return 'url:sha1:{self.commit.hexsha}'.format(self=self)

    @_label.default
    def default_label(self):
        """Generate a default label."""
        return self.commit.message.split('\n')[0]

    @outputs.default
    def default_outputs(self):
        """Guess default outputs from a commit."""
        return {path: None for path in self.commit.stats.files.keys()}

    @started_at_time.default
    def default_started_at_time(self):
        """Configure calculated properties."""
        return datetime.fromtimestamp(self.commit.authored_date).isoformat()

    @ended_at_time.default
    def default_ended_at_time(self):
        """Configure calculated properties."""
        return datetime.fromtimestamp(self.commit.committed_date).isoformat()

    def change_key(self, dependency, path=None):
        """Rename the path part in the key."""
        path = path or dependency.path
        return str(dependency.commit), path

    def iter_nodes(self):
        """Yield all graph nodes."""
        for path, _ in self.outputs.items():
            data = {
                'commit': self.commit,
                'path': path,
                'submodule': self.submodules,
                'client': self.client,
            }
            yield (str(self.commit), path), data

    def iter_edges(self):
        """Yield all graph edges."""
        return
        yield  # empty generator

    def pred(self, path):
        """Return a list of parents."""
        return []

    @staticmethod
    def from_git_commit(commit, client, process_path=None, submodules=None):
        """Populate information from the given Git commit."""
        return from_git_commit(
            commit, client, process_path=None, submodules=submodules
        )


@jsonld.s(
    type='wfprov:ProcessRun',
    context={
        'wfprov': 'http://purl.org/wf4ever/wfprov#',
    },
)
class ProcessRun(Activity):
    """A process run is a particular execution of a Process description."""

    # process_path = wfprov:describedByProcess
    # wfprov:wasPartOfWorkflowRun

    inputs = attr.ib()
    outputs = attr.ib()

    _id = jsonld.ib(context='@id', init=False)

    qualified_usage = jsonld.ib(context='prov:qualifiedUsage')

    @_id.default
    def default_id(self):
        """Configure calculated ID."""
        return 'url:sha1:{self.commit.hexsha}#{self.process_path}'.format(
            self=self
        )

    @inputs.default
    def default_inputs(self):
        """Guess default inputs from a process."""
        basedir = os.path.dirname(self.process_path)
        commit = self.commit
        client = self.client
        process = self.process
        hierarchy = self.submodules

        inputs = {}
        revision = '{0}^'.format(commit)

        try:
            from git import Submodule

            submodules = [
                submodule for submodule in
                Submodule.iter_items(client.git, parent_commit=commit)
            ]
        except (RuntimeError, ValueError):
            # There are no submodules assiciated with the given commit.
            submodules = []

        subclients = {
            submodule: LocalClient(
                path=(client.path / submodule.path).resolve(),
                parent=client,
            )
            for submodule in submodules
        }

        def resolve_submodules(file_, **kwargs):
            original_path = client.path / file_
            if original_path.is_symlink(
            ) or file_.startswith('.renku/vendors'):
                original_path = original_path.resolve()
                for submodule, subclient in subclients.items():
                    try:
                        subpath = original_path.relative_to(subclient.path)
                        return Dependency.from_revision(
                            client=subclient,
                            path=str(subpath),
                            revision=submodule.hexsha,
                            submodules=hierarchy + [submodule.name],
                            **kwargs
                        )
                    except ValueError:
                        pass

        for input_id, input_path in process.iter_input_files(basedir):
            try:
                dependency = resolve_submodules(input_path, id=input_id)
                if dependency is None:
                    dependency = Dependency.from_revision(
                        client=client,
                        path=input_path,
                        id=input_id,
                        revision=revision,
                    )
                inputs[input_path] = dependency
            except KeyError:
                continue

        return inputs

    @qualified_usage.default
    def default_qualified_usage(self):
        """Generate list of used artifacts."""
        return list(self.inputs.values())

    @outputs.default
    def default_outputs(self):
        """Guess default outputs from a process."""
        basedir = os.path.dirname(self.process_path)
        tree = DirectoryTree.from_list((
            path for path in super(ProcessRun, self).default_outputs()
            if not self.client.is_cwl(path)
        ))
        outputs = {}

        for output_id, output_path in self.process.iter_output_files(
            basedir, commit=self.commit
        ):
            outputs[output_path] = output_id

            # Expand directory entries.
            for subpath in tree.get(output_path, []):
                outputs.setdefault(
                    os.path.join(output_path, subpath), output_id
                )

        return outputs

    def iter_nodes(self):
        """Yield all graph nodes."""
        yield from super(ProcessRun, self).iter_nodes()

        data = {
            'client': self.client,
            'commit': self.commit,
            'path': self.process_path,
            'tool': self.process,
            'submodule': self.submodules,
        }
        # TODO submodule
        yield (str(self.commit), self.process_path), data

        for path, dependency in self.inputs.items():
            data = {
                'commit': dependency.commit,
                'path': dependency.path,
                'submodule': dependency.submodules,
                'client': dependency.client,
            }
            yield self.change_key(dependency, path=path), data

    def iter_edges(self):
        """Yield all graph edges."""
        tool_key = (str(self.commit), self.process_path)
        for path, dependency in self.inputs.items():
            input_key = self.change_key(dependency, path=path)
            #: Edge from an input to the tool.
            yield input_key, tool_key, {'id': dependency.id}

        for path, output_id in self.outputs.items():
            node_key = (str(self.commit), path)
            #: Edge from the tool to an output.
            yield tool_key, node_key, {'id': output_id}

    def pred(self, path):
        """Return a list of parents."""
        if path == self.process_path:
            return [
                self.change_key(dependency, path=path)
                for path, dependency in self.inputs.items()
            ]
        assert path in self.outputs
        return [(self.commit.hexsha, self.process_path)]


@jsonld.s(
    type='wfprov:WorkflowRun',
    context={
        'wfprov': 'http://purl.org/wf4ever/wfprov#',
    },
)
class WorkflowRun(ProcessRun):
    """A workflow run typically contains several subprocesses."""

    # @reverse wfprov:wasPartOfWorkflowRun

    children = attr.ib(init=False)

    subprocesses = jsonld.ib(
        context={
            '@reverse': 'wfprov:wasPartOfWorkflowRun',
        }, init=False
    )

    @children.default
    def default_children(self):
        """Load children from process."""
        return self.process._tools

    @subprocesses.default
    def default_subprocesses(self):
        """Load subprocesses."""
        basedir = os.path.dirname(self.process_path)
        revision = '{0}^'.format(self.commit)

        subprocesses = {}

        for step in self.process.steps:
            path = os.path.join(basedir, step.run)
            process = self.children[step.id]

            if process.__class__.__name__ == 'Workflow':
                cls = WorkflowRun
            else:
                cls = ProcessRun

            subprocess = cls(
                commit=self.client.find_previous_commit(
                    path, revision=revision
                ),
                client=self.client,
                process=process,
                process_path=path,
                submodules=self.submodules,
            )
            subprocesses[path] = (step, subprocess)

        return subprocesses

    def iter_nodes(self):
        """Yield all graph nodes."""
        basedir = os.path.dirname(self.process_path)
        default_data = {
            'client': self.client,
            'workflow': self.process,
            'submodule': self.submodules,
        }
        revision = '{0}^'.format(self.commit)

        for step in reversed(self.process.steps):
            step_id = step.id
            subprocess = self.children[step_id]
            path = os.path.join(basedir, step.run)
            # The workflow path must be relative to the current tool
            # since we might be inside a submodule.
            workflow_path = os.path.relpath(
                self.process_path, start=os.path.dirname(path)
            )

            step_outputs = self.process._step_outputs.get(step_id)
            if step_outputs is not None:
                step_outputs = step_outputs.items()
            else:
                step_outputs = subprocess.iter_output_files(
                    basedir, commit=self.commit
                )

            for _, output_path in step_outputs:
                data = {
                    'commit': self.commit,
                    'path': output_path,
                    'submodule': self.submodules,
                    'client': self.client,
                }
                yield (str(self.commit), output_path), data

            data = {
                'path': path,
                'commit':
                    self.client.find_previous_commit(path, revision=revision),
                'tool': subprocess,
                'workflow_path':
                    '{workflow_path}#steps/{step.id}'
                    .format(workflow_path=workflow_path, step=step),
            }
            data.update(**default_data)
            yield (str(self.commit), path), data

        for path, dependency in self.inputs.items():
            data = {
                'commit': dependency.commit,
                'path': dependency.path,
                'submodule': dependency.submodules,
                'client': dependency.client,
            }
            yield self.change_key(dependency, path=path), data

    def iter_edges(self):
        """Yield all graph edges."""
        commit = self.commit
        workflow = self.process
        basedir = os.path.dirname(self.process_path)

        # Keep track of node identifiers for steps, inputs and outputs:
        step_map = {}
        input_map = {
            dep.id: (str(dep.commit), path)
            for path, dep in self.inputs.items()
        }
        output_map = {}

        for step in workflow.steps:
            step_tool = self.children[step.id]
            tool_path = os.path.join(basedir, step.run)
            tool_key = (str(commit), tool_path)
            step_map[step.id] = tool_key

            for input_id, input_path in step_tool.iter_input_files(basedir):
                if input_path in commit.stats.files:
                    #: Check intermediate committed files
                    input_key = (str(commit), input_path)
                    output_map[step.id + '/' + input_id] = input_key
                    #: Edge from an input to the tool.
                    yield input_key, tool_key, {'id': input_id}
                else:
                    #: Global workflow input
                    source = step.in_[input_id]
                    yield input_map[source], tool_key, {'id': input_id}

            # Find ALL siblings that MUST be generated in the same commit.
            step_outputs = workflow._step_outputs.get(step.id)
            if step_outputs is not None:
                step_outputs = step_outputs.items()
            else:
                step_outputs = step_tool.iter_output_files(
                    basedir, commit=commit
                )

            for output_id, output_path in step_outputs:
                node_key = (str(commit), output_path)
                yield tool_key, node_key, {'id': output_id}

        for step in workflow.steps:
            for alias, source in step.in_.items():
                name = step.id + '/' + alias

                if name in output_map and '/' in source:
                    other_step, id_ = source.split('/')
                    other_key = step_map[other_step]
                    yield other_key, output_map[name], {'id': id_}

    def pred(self, path):
        """Return a list of parents."""
        parents = []
        ins = {
            dependency.id: dependency
            for path, dependency in self.inputs.items()
        }
        outputs_ = {id_: path_ for path_, id_ in self.outputs.items()}
        outs = {
            output.outputSource: outputs_[output.id]
            for output in self.process.outputs
        }

        if path in self.subprocesses:
            step, activity = self.subprocesses[path]

            for alias, source in step.in_.items():
                if source in ins:
                    dependency = ins[source]
                    parents.append((dependency.commit.hexsha, dependency.path))
                elif source in outs:
                    parents.append((self.commit.hexsha, outs[source]))
                elif ins:
                    raise NotImplemented()

        elif path in self.outputs:
            # TODO consider recursive call to subprocesses
            output_id = self.outputs[path]
            output = next(
                output
                for output in self.process.outputs if output.id == output_id
            )
            step_id, _, source = output.outputSource.partition('/')
            step_path = next(
                path_ for path_, (step, activity) in self.subprocesses.items()
                if step.id == step_id
            )
            parents.append((self.commit.hexsha, step_path))

        else:
            raise NotImplemented()

        return parents


def from_git_commit(commit, client, process_path=None, submodules=None):
    """Populate information from the given Git commit."""
    cls = Activity
    process = None
    hierarchy = list(submodules) if submodules else []

    if process_path is None:
        for file_ in commit.stats.files.keys():
            # 1.a Find process (CommandLineTool or Workflow);
            if client.is_cwl(file_):
                if process_path is not None:
                    raise ValueError(file_)  # duplicate
                process_path = file_
                continue
    else:
        assert process_path in set(commit.stats.files.keys())

    if process_path:
        try:
            data = (commit.tree / process_path).data_stream.read()
            process = CWLClass.from_cwl(yaml.load(data))

            if process.__class__.__name__ == 'Workflow':
                cls = WorkflowRun
            else:
                cls = ProcessRun

            return cls(
                commit=commit,
                client=client,
                process=process,
                process_path=process_path,
                submodules=hierarchy,
            )
        except KeyError:
            pass

    return cls(commit=commit, client=client, submodules=hierarchy)
