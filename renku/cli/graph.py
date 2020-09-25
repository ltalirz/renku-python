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
from collections import defaultdict
from pathlib import Path

import click
from git import GitCommandError, NULL_TREE

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

    # commits = list(commits)[2810:]

    if force:
        try:
            client.dependency_graph_path.unlink()
        except FileNotFoundError:
            pass
        try:
            client.provenance_graph_path.unlink()
        except FileNotFoundError:
            pass
    else:
        if client.dependency_graph_path.exists() or client.provenance_graph_path.exists():
            raise RuntimeError(f"Graph files exist. Use --force to regenerate the graph.")

    dependency_graph = DependencyGraph.from_json(client.dependency_graph_path)
    provenance_graph = ProvenanceGraph.from_json(client.provenance_graph_path)

    # client.provenance_path.mkdir(exist_ok=True)

    for n, commit in enumerate(commits):
        print(f"\rProcessing commits {n}/{n_commits}\r", end="", file=sys.stderr)

        for file_ in commit.diff(commit.parents or NULL_TREE):
            # Ignore deleted files (they appear as ADDED in this backwards diff)
            if file_.change_type == "A":
                continue

            path: str = file_.a_path

            if not path.startswith(".renku/workflow") or not path.endswith(".yaml"):
                continue

            # target_path = client.provenance_path / f"{Path(path).stem}.json"
            # if target_path.exists():
            #     raise RuntimeError(f"Target file exists: {target_path}. Use --force to regenerate the graph.")

            # print(f"\rProcessing commits {n}/{n_commits} workflow file: {os.path.basename(path)}\r", file=sys.stderr)

            workflow = ActivityRun.from_yaml(path=path, client=client)
            activity_collection = ActivityCollection.from_activity_run(workflow, dependency_graph, client)

            # activity_collection.to_json(path=target_path)
            provenance_graph.add(activity_collection)

    dependency_graph.to_json()
    provenance_graph.to_json()


@graph.command()
@click.argument("paths", type=click.Path(exists=True, dir_okay=False), nargs=-1)
@pass_local_client(requires_migration=False)
@click.pass_context
def status(ctx, client, paths):
    r"""Equivalent of `renku status`."""
    with measure("BUILD AND QUERY GRAPH"):
        pg = ProvenanceGraph.from_json(client.provenance_graph_path, lazy=True)
        usages = pg.get_latest_usages_path_and_checksum()

    print(usages)

    with measure("CALCULATE MODIFIED"):
        modified, deleted = _get_modified_paths(client=client, path_and_checksum=usages)

    if not modified and not deleted:
        print("OK")

    stales = defaultdict(set)

    with measure("CALCULATE UPDATES"):
        dg = DependencyGraph.from_json(client.dependency_graph_path)
        for path in modified:
            paths = dg.get_dependent_paths(path)
            for p in paths:
                stales[p].add(path)

    print(f"Updates: {len(stales)}", "".join(sorted([f"\n\t{k}: {', '.join(sorted(v))}" for k, v in stales.items()])))
    print()
    print(f"Modified: {len(modified)}", "".join(sorted([f"\n\t{e}" for e in modified])))
    print()
    print(f"Deleted: {len(deleted)}", "".join(sorted([f"\n\t{e}" for e in deleted])))


def _get_modified_paths(client, path_and_checksum):
    modified = set()
    deleted = set()
    for path, checksum in path_and_checksum:
        try:
            current_checksum = client.repo.git.rev_parse(f"HEAD:{str(path)}")
        except GitCommandError:
            deleted.add(path)
        else:
            if current_checksum != checksum:
                modified.add(path)

    return modified, deleted

