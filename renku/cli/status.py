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
"""Show status of data files created in the repository.

Inspecting a repository
~~~~~~~~~~~~~~~~~~~~~~~

Displays paths of outputs which were generated from newer inputs files
and paths of files that have been used in diverent versions.

The first paths are what need to be recreated by running ``renku update``.
See more in section about :ref:`renku update <cli-update>`.

The paths mentioned in the output are made relative to the current directory
if you are working in a subdirectory (this is on purpose, to help
cutting and pasting to other commands). They also contain first 8 characters
of the corresponding commit identifier after the ``#`` (hash). If the file was
imported from another repository, the short name of is shown together with the
filename before ``@``.
"""
from contextlib import contextmanager

import click

from renku.core.commands.ascii import _format_sha1
from renku.core.commands.client import pass_local_client
from renku.core.commands.graph import Graph
from renku.core.models.provenance.provenance_graph import ProvenanceGraph, ALL_USAGES


@click.command()
@click.option("--new", is_flag=True, help="Use new graph model.")
@click.option("--revision", default="HEAD", help="Display status as it was in the given revision")
@click.option("--no-output", is_flag=True, default=False, help="Display commands without output files.")
@click.argument("path", type=click.Path(exists=True, dir_okay=False), nargs=-1)
@pass_local_client(clean=True, requires_migration=True, commit=False)
@click.pass_context
def status(ctx, client, revision, no_output, path, new):
    """Show a status of the repository."""
    if not new:
        graph = Graph(client)
        # TODO filter only paths = {graph.normalize_path(p) for p in path}
        status = graph.build_status(revision=revision, can_be_cwl=no_output)
    else:
        status = _build_new_status(client)
        return

    if client.has_external_files():
        click.echo(
            "Changes in external files are not detected automatically. To "
            'update external files run "renku dataset update -e".'
        )

    try:
        click.echo("On branch {0}".format(client.repo.active_branch))
    except TypeError:
        click.echo("Git HEAD is detached!\n" " Please move back to your working branch to use renku\n")
    if status["outdated"]:
        click.echo(
            "Outdated outputs:\n"
            '  (use "renku log [<file>...]" to see the full lineage)\n'
            '  (use "renku update [<file>...]" to '
            "generate the file from its latest inputs)\n"
        )

        for filepath, stts in sorted(status["outdated"].items()):
            outdated = ", ".join(
                "{0}#{1}".format(click.style(graph._format_path(n.path), fg="blue", bold=True), _format_sha1(graph, n),)
                for n in stts
                if n.path and n.path not in status["outdated"]
            )

            click.echo("\t{0}: {1}".format(click.style(graph._format_path(filepath), fg="red", bold=True), outdated))

        click.echo()

    else:
        click.secho("All files were generated from the latest inputs.", fg="green")

    if status["multiple-versions"]:
        click.echo(
            "Modified inputs:\n"
            '  (use "renku log --revision <sha1> <file>" to see a lineage '
            "for the given revision)\n"
        )

        for filepath, files in sorted(status["multiple-versions"].items()):
            # Do not show duplicated commits!  (see #387)
            commits = {_format_sha1(graph, key) for key in files}
            click.echo(
                "\t{0}: {1}".format(
                    click.style(graph._format_path(filepath), fg="blue", bold=True),
                    ", ".join(
                        # Sort the commit hashes alphanumerically to have a
                        # predictable output.
                        sorted(commits)
                    ),
                )
            )

        click.echo()

    if status["deleted"]:
        click.echo(
            "Deleted files used to generate outputs:\n"
            '  (use "git show <sha1>:<file>" to see the file content '
            "for the given revision)\n"
        )

        for filepath, node in status["deleted"].items():
            click.echo(
                "\t{0}: {1}".format(
                    click.style(graph._format_path(filepath), fg="blue", bold=True), _format_sha1(graph, node)
                )
            )

        click.echo()

    ctx.exit(1 if status["outdated"] else 0)


def _build_new_status(client):
    with measure("LOADED"):
        provenance_graph = ProvenanceGraph.from_yaml(client.provenance_graph_path)

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


@contextmanager
def measure(message="TOTAL"):
    import time

    start = time.time()
    try:
        yield
    finally:
        end = time.time()
        total_seconds = float("%.2f" % (end - start))
        print(f"{message}: {total_seconds} seconds")
