#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

# These lines allow to use UTF-8 encoding and run this file with `./update.py`, instead of `python update.py`
# https://stackoverflow.com/questions/7670303/purpose-of-usr-bin-python3
# https://stackoverflow.com/questions/728891/correct-way-to-define-python-source-code-encoding
#
#

#
# Licensing
#
# Channel Manager Copier, Unpack the Default.sublime-package and configure it
# Copyright (C) 2017 Evandro Coan <https://github.com/evandrocoan>
#
#  This program is free software; you can redistribute it and/or modify it
#  under the terms of the GNU General Public License as published by the
#  Free Software Foundation; either version 3 of the License, or ( at
#  your option ) any later version.
#
#  This program is distributed in the hope that it will be useful, but
#  WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
#  General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import sublime
import configparser

import os
import sys
import zipfile
import threading
import contextlib

from . import settings as g_settings
from .channel_utilities import is_sublime_text_upgraded


from python_debug_tools import Debugger

# Debugger settings: 0 - disabled, 127 - enabled
log = Debugger( 127, os.path.basename( __file__ ) )

# log( 2, "..." )
# log( 2, "..." )
# log( 2, "Debugging" )
# log( 2, "CURRENT_PACKAGE_ROOT_DIRECTORY: " + g_settings.CURRENT_PACKAGE_ROOT_DIRECTORY )


def main(default_package_files=[], is_forced=False):

    # We can only run this when we are using the development version of the channel. And when there
    # is a `.git` folder, we are running the `Development Version` of the channel.
    main_git_path = os.path.join( g_settings.CURRENT_PACKAGE_ROOT_DIRECTORY, ".git" )

    # Not attempt to run when we are running from inside a `.sublime-package` because this is only
    # available for the `Development Version` as there is not need to unpack the `Default Package`
    # on the `Stable Version` of the channel.
    if is_forced or os.path.exists( main_git_path ) and is_sublime_text_upgraded( "copy_default_package" ):
        log( 1, "Entering on CopyFilesThread(1)" )
        CopyFilesThread( default_package_files ).start()


class CopyFilesThread(threading.Thread):

    def __init__(self, default_package_files):
        threading.Thread.__init__(self)
        self.default_package_files = default_package_files

    def run(self):
        log( 2, "Entering on run(1)" )

        package_path  = os.path.join( os.path.dirname( sublime.executable_path() ), "Packages", "Default.sublime-package" )
        output_folder = os.path.join( os.path.dirname( sublime.packages_path() ), "Default.sublime-package" )

        log( 2, "run, package_path:  " + package_path )
        log( 2, "run, output_folder: " + output_folder )

        extract_package( package_path, output_folder )
        create_git_ignore_file( output_folder, self.default_package_files )


def create_git_ignore_file(output_folder, default_package_files):

    if len( default_package_files ) < 1:
        log( 1, "Skipping creating `.gitignore` file as not files are passed to the main function." )
        return

    gitignore_file = os.path.join( output_folder, ".gitignore" )
    lines_to_write = \
    [
        "",
        "# Do not edit this file manually, otherwise your changes will be lost on the next update!",
        "# To change this file contents, edit the package `%s/%s`" % ( g_settings.CURRENT_PACKAGE_NAME, os.path.basename( __file__ ) ),
        "",
        "",
        "# Ignore everything",
        "*",
        "**",
        "",
        "# Only accept the unchanged files, need to add new files here manually",
    ]

    for file in default_package_files:
        lines_to_write.append( "!" + file )

    lines_to_write.append("\n")
    log( 1, "Writing to gitignore_file: " + str( gitignore_file ) )

    with open( gitignore_file, "w" ) as text_file:
        text_file.write( "\n".join( lines_to_write ) )


def extract_package(package_path, destine_folder):
    """
        If the files already exists on the destine, they will be overridden.
    """

    try:
        package_file = zipfile.ZipFile( package_path )

    except zipfile.BadZipfile as error:
        log( 1, " The package file '%s is invalid! Error: %s" % ( package_path, error ) )

    with contextlib.closing( package_file ):

        try:
            os.mkdir( destine_folder )

        except OSError as error:

            if os.path.isdir( destine_folder ):
                pass

            else:
                log( 1, "The directory '%s' could not be created! Error: %s" % ( destine_folder, error ) )
                return

        try:
            package_file.extractall( destine_folder )

        except Exception as error:
            log( 1, "Extracting '%s' failed. Error: %s" % ( package_path, error ) )
            return

        log( 1, "The file '%s' was successfully extracted." % package_path )


if __name__ == "__main__":
    main()


