# -*- coding: utf-8 -*-
#
# Copyright 2018-2020- Swiss Data Science Center (SDSC)
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
"""PoC command for testing the new graph design."""
from pathlib import Path

import click

from renku.core.commands.client import pass_local_client
from renku.core.management.config import RENKU_HOME
from renku.core.models.provenance.provenance_graph import ProvenanceGraph, ALL_USAGES
from renku.core.utils.contexts import measure


GRAPH_METADATA_PATHS = [
    Path(RENKU_HOME) / Path(DatasetsApiMixin.DATASETS),
    Path(RENKU_HOME) / Path(DatasetsApiMixin.POINTERS),
    Path(RENKU_HOME) / Path(LinkReference.REFS),
    ".gitattributes",
]


@click.group()
def graph():
    """PoC command for testing the new graph design."""


@graph.command()
@click.option("-f", "--force", is_flag=True, help="Delete existing metadata and regenerate all.")
@pass_local_client(requires_migration=True, commit=True, commit_empty=False, commit_only=GRAPH_METADATA_PATHS)
def generate(client, force):
    """Create new graph metadata."""
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


@graph.command()
@click.argument("paths", type=click.Path(exists=True, dir_okay=False), nargs=-1)
@pass_local_client(requires_migration=False)
@click.pass_context
def status(ctx, client, paths):
    r"""Equivalent of `renku status`."""
    with measure("LOADED"):
        provenance_graph = ProvenanceGraph.from_json(client.provenance_graph_path)

    use_sparql = False

    if use_sparql:
        with measure("GRAPH GENERATED"):
            graph = provenance_graph.to_conjunctive_graph()

        with measure("GRAPH QUERIED"):
            result = graph.query(ALL_USAGES)

            latest = {}

            for path, checksum, order in result:
                max_order, _ = latest.get(path, (-1, -1))
                if int(order) > max_order:
                    latest[path] = (int(order), checksum)
    else:
        with measure("CALCULATE RESULTS"):
            latest = {}

            for activity in provenance_graph.activities.values():
                for e in activity.qualified_usage:
                    max_order, _ = latest.get(e.path, (-1, -1))
                    if int(activity.order) > max_order:
                        latest[e.path] = (activity.order, e.checksum)

    # for path in latest:
    #     order, checksum = latest.get(path, (-1, -1))
    #     print(path, checksum, order)

    print(len(latest))
