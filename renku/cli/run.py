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
"""Track provenance of data created by executing programs.

Capture command line execution
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Tracking exection of your command line script is done by simply adding the
``renku run`` command before the previous arguments. The command will detect:

* arguments (flags),
* string and integer options,
* input files if linked to existing files in the repository,
* output files if modified or created while running the command.

.. note:: If there were uncommitted changes then the command fails.
   See :program:`git status` for details.

Detecting input files
~~~~~~~~~~~~~~~~~~~~~

An argument is identified as an input file only if its path matches an existing
file in the repository. There might be several situations when the detection
might not work as expected:

* If the file is modified during the execution, then it is stored as an output;
* If the path points to a directory, then it is stored as a string option;
* The input file is not defined as the tool argument.

Detecting output files
~~~~~~~~~~~~~~~~~~~~~~

Any file which is modified or created after the execution will be added as an
output. If the program does not produce any outputs, you can specify the
``--no-output`` option.

There might be situations where an existing output file has not been changed
when the command has been executed with different parameters. The execution
ends with an error: ``Error: There are not any detected outputs in the
repository.`` In order to resolve it remove any proposed input file from the
list first.

.. cli-run-std

Detecting standard streams
~~~~~~~~~~~~~~~~~~~~~~~~~~

Often the program expect inputs as a standard input stream. This is detected
and recorded in the tool specification when invoked by ``renku run cat < A``.

Similarly, both redirects to standard output and standard error output can be
done when invoking a command:

.. code-block:: console

   $ renku run grep "test" B > C 2> D

.. warning:: Detecting inputs and outputs from pipes ``|`` is not supported.
"""

import os
import sys
from subprocess import call

import click

from renku.models.cwl.command_line_tool import CommandLineToolFactory

from ._client import pass_local_client
from ._git import _mapped_std_streams, with_git


@click.command(context_settings=dict(ignore_unknown_options=True, ))
@click.option(
    '--no-output',
    is_flag=True,
    default=False,
    help='Allow commands without output files.'
)
@click.argument('command_line', nargs=-1, type=click.UNPROCESSED)
@pass_local_client
@with_git(clean=True, up_to_date=True, commit=True, ignore_std_streams=True)
def run(client, no_output, command_line):
    """Tracking work on a specific problem."""
    working_dir = client.git.working_dir
    candidates = [
        os.path.join(working_dir, path)
        for path in [x[0] for x in client.git.index.entries] +
        client.git.untracked_files
    ]
    mapped_std = _mapped_std_streams(candidates)
    factory = CommandLineToolFactory(
        command_line=command_line,
        directory=working_dir,
        **{
            name: os.path.relpath(path, working_dir)
            for name, path in mapped_std.items()
        }
    )

    with client.with_workflow_storage() as wf:
        with factory.watch(client, no_output=no_output) as tool:
            call(
                factory.command_line,
                cwd=os.getcwd(),
                **{key: getattr(sys, key)
                   for key in mapped_std.keys()},
            )

            sys.stdout.flush()
            sys.stderr.flush()

            wf.add_step(run=tool)
