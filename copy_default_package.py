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

import os
import sys
import zipfile
import threading
import contextlib


# https://stackoverflow.com/questions/14087598/python-3-importerror-no-module-named-configparser
try:
    import configparser
    from configparser import NoOptionError

except:
    from six.moves import configparser
    from six.moves.configparser import NoOptionError


from .settings import *
UPGRADE_SESSION_FILE = os.path.join( CURRENT_DIRECTORY, 'last_sublime_upgrade.studio-channel' )

# Import the debugger
from debug_tools import Debugger

# Debugger settings: 0 - disabled, 127 - enabled
log = Debugger( 1, os.path.basename( __file__ ) )

log( 2, "..." )
log( 2, "..." )
log( 2, "Debugging" )
log( 2, "CURRENT_DIRECTORY: " + CURRENT_DIRECTORY )


def main(default_packages_files=[]):
    log( 2, "Entering on main(0)" )

    # Not attempt to run when we are running from inside a `.sublime-package`: FileNotFoundError:
    # '..\\Installed Packages\\ChannelManager.sublime-package\\last_sublime_upgrade.studio-channel'
    if os.path.isdir( CURRENT_DIRECTORY ) and is_sublime_text_upgraded():
        CopyFilesThread( default_packages_files ).start()


class CopyFilesThread(threading.Thread):

    def __init__(self, default_packages_files):
        threading.Thread.__init__(self)
        self.default_packages_files = default_packages_files

    def run(self):
        log( 2, "Entering on run(1)" )

        package_path  = os.path.join( os.path.dirname(sublime.executable_path()), "Packages", "Default.sublime-package" )
        output_folder = os.path.join( os.path.dirname( os.path.dirname( CURRENT_DIRECTORY ) ), "Default.sublime-package" )

        log( 2, "run, package_path:  " + package_path )
        log( 2, "run, output_folder: " + output_folder )

        extract_package( package_path, output_folder )
        create_git_ignore_file( output_folder, self.default_packages_files )


def create_git_ignore_file(output_folder, default_packages_files):

    if len( default_packages_files ) < 1:
        log( 1, "Skipping creating `.gitignore` file as not files are passed to the main function." )
        return

    gitignore_file = os.path.join( output_folder, ".gitignore" )
    lines_to_write = \
    [
        "",
        "# Do not edit this file manually, otherwise your changes will be lost on the next update!",
        "# To change this file contents, edit the package `%s/%s`" % ( CURRENT_PACKAGE_NAME, os.path.basename( __file__ ) ),
        "",
        "",
        "# Ignore everything",
        "*",
        "**",
        "",
        "# Only accept the unchanged files, need to add new files here manually",
    ]

    for file in default_packages_files:
        lines_to_write.append( "!" + file )

    lines_to_write.append("\n")

    with open( gitignore_file, "w" ) as text_file:
        text_file.write( "\n".join( lines_to_write ) )


def extract_package(package_path, destine_folder):
    """
        If the files already exists on the destine, they will be overridden.
    """

    try:
        package_file = zipfile.ZipFile(package_path)

    except zipfile.BadZipfile:
        log( 1, " The package file '%s is invalid!" % package_path)

    with contextlib.closing(package_file):

        try:
            os.mkdir(destine_folder)

        except OSError:

            if os.path.isdir(destine_folder):
                pass

            else:
                log( 1, "The directory '%s' could not be created!" % destine_folder)
                return

        try:
            package_file.extractall(destine_folder)

        except:
            log( 1, "Extracting '%s' failed." % package_path)
            return

        log( 2, "The file '%s' was successfully extracted." % package_path)


def is_sublime_text_upgraded():
    """
        @return True   when it is the fist time this function is called or there is a sublime text
                       upgrade, False otherwise.
    """

    current_version = int( sublime.version() )

    last_section = open_last_session_data( UPGRADE_SESSION_FILE )
    last_version = int( last_section.getint( 'last_sublime_text_version', 'integer_value' ) )

    last_section.set( 'last_sublime_text_version', 'integer_value', str( current_version ) )
    save_session_data( last_section, UPGRADE_SESSION_FILE )

    if last_version < current_version:
        return True

    else:
        return False


def open_last_session_data(session_file):
    last_section = configparser.ConfigParser( allow_no_value=True )

    if os.path.exists( session_file ):
        last_section.read( session_file )

    else:
        last_section.add_section( 'last_sublime_text_version' )
        last_section.set( 'last_sublime_text_version', 'integer_value', '0' )

    return last_section


def save_session_data(last_section, session_file):

    with open( session_file, 'wt' ) as configfile:
        last_section.write( configfile )


if __name__ == "__main__":
    main()


