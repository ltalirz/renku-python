# -*- coding: utf-8 -*-
#
# Copyright 2020 - Swiss Data Science Center (SDSC)
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
"""Initial migrations."""

from pathlib import Path

from git import NULL_TREE

from renku.core.models.provenance import activities
from renku.core.models.provenance.activities import WorkflowRun
from renku.core.models.provenance.activity import Activity, ActivityCollection
from renku.core.models.provenance.provenance_graph import ProvenanceGraph
from renku.core.models.workflow.dependency_graph import DependencyGraph
from renku.core.models.workflow.plan import Plan


def migrate(client):
    """Migration function."""
    _migrate_old_workflows(client)


def _migrate_old_workflows(client):
    """Create graphs from workflows."""
    commits = list(client.repo.iter_commits())
    n_commits = len(commits)
    commits = reversed(commits)
    n = 1

    dependency_graph = DependencyGraph.from_json(client.dependency_graph_path)
    # provenance_graph = ProvenanceGraph.from_json(client.provenance_graph_path)

    order = 1

    for commit in commits:
        print(f"\rProcessing commits ({n}/{n_commits})", end="")

        order = _process_commit(commit, client=client, dependency_graph=dependency_graph, order=order)

        n += 1

    dependency_graph.to_json()
    # provenance_graph.to_json()


def _process_commit(commit, client, dependency_graph, order):
    for file_ in commit.diff(commit.parents or NULL_TREE):
        # Ignore process deleted files (note they appear as ADDED) in this backwards diff
        if file_.change_type == "A":
            continue

        path: str = file_.a_path

        if not path.startswith(".renku/workflow") or not path.endswith(".yaml"):
            continue

        workflow = activities.Activity.from_yaml(path=path, client=client)

        # TODO this is not correct because workflow._processes is an array and there is no guaranty that it will be
        # deserialized in order
        subprocesses = list(workflow.subprocesses.items()) if isinstance(workflow, WorkflowRun) else [(0, workflow)]
        subprocesses.sort()

        path = f".renku/provenance/{Path(path).name}"
        Path(path).parent.mkdir(exist_ok=True)
        activity_collection = ActivityCollection()

        for _, process_run in subprocesses:
            run = process_run.association.plan
            if run.subprocesses:
                assert len(run.subprocesses) == 1
                run = run.subprocesses[0]

            plan = Plan.from_run(run=run, name=None)
            plan = dependency_graph.find_similar_plan(plan) or plan
            dependency_graph.add(plan)

            process_run = run.activity

            activity = Activity.from_process_run(
                process_run=process_run, path=Path(path), plan=plan, client=client, order=order
            )
            order += 1
            activity_collection.add(activity)

        activity_collection.to_json(path)

    return order
