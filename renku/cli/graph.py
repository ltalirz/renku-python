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
import os
import sys
from pathlib import Path

import click
from git import NULL_TREE

from renku.core.commands.client import pass_local_client
from renku.core.management.config import RENKU_HOME
from renku.core.management.repository import RepositoryApiMixin
from renku.core.models.provenance.activities import Activity as ActivityRun, WorkflowRun
from renku.core.models.provenance.activity import ActivityCollection, Activity
from renku.core.models.provenance.provenance_graph import ProvenanceGraph, ALL_USAGES
from renku.core.models.workflow.dependency_graph import DependencyGraph
from renku.core.models.workflow.plan import Plan
from renku.core.utils.contexts import measure


GRAPH_METADATA_PATHS = [
    Path(RENKU_HOME) / Path(RepositoryApiMixin.DEPENDENCY_GRAPH),
    Path(RENKU_HOME) / Path(RepositoryApiMixin.PROVENANCE),
    Path(RENKU_HOME) / Path(RepositoryApiMixin.PROVENANCE_GRAPH),
]


@click.group()
def graph():
    """PoC command for testing the new graph design."""


@graph.command()
@click.option("-f", "--force", is_flag=True, help="Delete existing metadata and regenerate all.")
@pass_local_client(requires_migration=True, commit=True, commit_empty=False, commit_only=GRAPH_METADATA_PATHS)
def generate(client, force):
    """Create new graph metadata."""
    commits = list(client.repo.iter_commits())
    n_commits = len(commits)
    commits = reversed(commits)

    # commits = list(commits)[2600:]

    dependency_graph = DependencyGraph.from_json(client.dependency_graph_path)
    order = 1
    client.provenance_path.mkdir(exist_ok=True)

    for n, commit in enumerate(commits):
        print(f"\rProcessing commits {n}/{n_commits}\r", end="", file=sys.stderr)

        for file_ in commit.diff(commit.parents or NULL_TREE):
            # Ignore deleted files (they appear as ADDED in this backwards diff)
            if file_.change_type == "A":
                continue

            path: str = file_.a_path

            if not path.startswith(".renku/workflow") or not path.endswith(".yaml"):
                continue

            # Do not process if a converted file exists
            target_path = client.provenance_path / f"{Path(path).stem}.json"
            if target_path.exists() and not force:
                # TODO: update order
                continue

            # print(f"\rProcessing commits {n}/{n_commits} workflow file: {os.path.basename(path)}\r", file=sys.stderr)

            workflow = ActivityRun.from_yaml(path=path, client=client)
            activities = ActivityCollection.from_activity_run(workflow, dependency_graph, client, first_order=order)

            activities.to_json(path=target_path)

            order = activities.max_order + 1

    dependency_graph.to_json()


@graph.command()
@click.argument("paths", type=click.Path(exists=True, dir_okay=False), nargs=-1)
@pass_local_client(requires_migration=False)
@click.pass_context
def status(ctx, client, paths):
    r"""Equivalent of `renku status`."""
    with measure("LOADED"):
        graph = ProvenanceGraph.to_graph(client.provenance_path)

    with measure("GRAPH QUERIED"):
        result = graph.query(ALL_USAGES)

    with measure("CALCULATE RESULTS"):
        print("RESULTS", len(result))
        latest = {}

        for path, checksum, order in result:
            max_order, _ = latest.get(path, (-1, -1))
            if int(order) > max_order:
                latest[path] = (int(order), checksum)

        for path in latest.keys():
            if not Path(path).exists():
                print(path)

    # use_sparql = False
    #
    # if use_sparql:
    #     with measure("GRAPH GENERATED"):
    #         graph = provenance_graph.to_conjunctive_graph()
    #
    #     with measure("GRAPH QUERIED"):
    #         result = graph.query(ALL_USAGES)
    #
    #         latest = {}
    #
    #         for path, checksum, order in result:
    #             max_order, _ = latest.get(path, (-1, -1))
    #             if int(order) > max_order:
    #                 latest[path] = (int(order), checksum)
    # else:
    #     with measure("CALCULATE RESULTS"):
    #         latest = {}
    #
    #         for activity in provenance_graph.activities.values():
    #             for e in activity.qualified_usage:
    #                 max_order, _ = latest.get(e.path, (-1, -1))
    #                 if int(activity.order) > max_order:
    #                     latest[e.path] = (activity.order, e.checksum)
    #
    # # for path in latest:
    # #     order, checksum = latest.get(path, (-1, -1))
    # #     print(path, checksum, order)
    #
    print(len(latest))
