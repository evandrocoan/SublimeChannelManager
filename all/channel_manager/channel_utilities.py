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
# Channel Manager Utilities, functions to be used by the common tasks
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

import os
import sys
import json
import stat

import re
import time
import textwrap


# Relative imports in Python 3
# https://stackoverflow.com/questions/16981921/relative-imports-in-python-3
try:
    from .settings import CURRENT_DIRECTORY
    from .settings import CURRENT_PACKAGE_NAME

except( ImportError, ValueError):
    from settings import CURRENT_DIRECTORY
    from settings import CURRENT_PACKAGE_NAME


# print_python_envinronment()
def assert_path(module):
    """
        Import a module from a relative path
        https://stackoverflow.com/questions/279237/import-a-module-from-a-relative-path
    """
    if module not in sys.path:
        sys.path.append( module )


# Allow using this file on the website where the sublime module is unavailable
try:
    import sublime

    # If a dependency fail running, the subsequent dependencies are not installed by Package Control
    # https://github.com/wbond/package_control/issues/1301
    try:
        from python_debug_tools import Debugger

        # Debugger settings: 0 - disabled, 127 - enabled
        log = Debugger( 127, os.path.basename( __file__ ) )

    except Exception as error:
        print( "Could not import PythonDebugTools! " + str( error ) )

except ImportError:
    sublime = None

    # Import the debugger. It will fail when `PythonDebugTools` is inside a `.sublime-package`,
    # however, this is only meant to be used on the Development version, when `PythonDebugTools` is
    # unpacked at the loose packages folder as a git submodule.
    assert_path( os.path.join( os.path.dirname( CURRENT_DIRECTORY ), 'PythonDebugTools/all' ) )
    from python_debug_tools import Debugger


def write_data_file(file_path, channel_dictionary):
    log( 1, "Writing to the data file: " + str( file_path ) )

    with open(file_path, 'w', encoding='utf-8') as output_file:
        json.dump( channel_dictionary, output_file, indent=4 )


def load_data_file(file_path, wait_on_error=True):
    """
        Attempt to read the file some times when there is a value error. This could happen when the
        file is currently being written by Sublime Text.
    """
    channel_dictionary = {}

    if os.path.exists( file_path ):
        error = None
        maximum_attempts = 10

        while maximum_attempts > 0:

            try:
                with open( file_path, 'r', encoding='utf-8' ) as data_file:
                    return json.load( data_file )

            except ValueError as error:
                log.insert_empty_line( 1 )
                log.insert_empty_line( 1 )

                log( 1, "Error, maximum_attempts %d, load_data_file: %s" % ( maximum_attempts, error ) )
                maximum_attempts -= 1

                if wait_on_error:
                    time.sleep( 0.1 )

        if maximum_attempts < 1:
            raise ValueError( "file_path: %s, error: %s" % ( file_path, error ) )

    else:
        log( 1, "Error on load_data_file(1), the file '%s' does not exists!" % file_path )

    return channel_dictionary


def string_convert_list( comma_separated_list ):

    if comma_separated_list:
        return [ dependency.strip() for dependency in comma_separated_list.split(',') ]

    return []


def get_main_directory(current_directory):
    possible_main_directory = os.path.normpath( os.path.dirname( os.path.dirname( current_directory ) ) )

    if sublime:
        sublime_text_packages = os.path.normpath( os.path.dirname( sublime.packages_path() ) )

        if possible_main_directory == sublime_text_packages:
            return possible_main_directory

        else:
            return sublime_text_packages

    return possible_main_directory


def print_data_file(file_path):
    channel_dictionary = load_data_file( file_path )
    log( 1, "channel_dictionary: " + json.dumps( channel_dictionary, indent=4, sort_keys=True ) )


def get_dictionary_key(dictionary, key, default=None):

    if key in dictionary:
        return dictionary[key]

    return default


def remove_if_exists(items_list, item):

    if item in items_list:
        items_list.remove( item )


def add_item_if_not_exists(list_to_append, item):

    if item not in list_to_append:
        list_to_append.append( item )


def remove_item_if_exists(list_to_remove, item):

    if item in list_to_remove:
        list_to_remove.remove( item )


def delete_read_only_file(path):
    _delete_read_only_file( None, path, None )


def _delete_read_only_file(action, name, exc):
    """
        shutil.rmtree to remove readonly files
        https://stackoverflow.com/questions/21261132/shutil-rmtree-to-remove-readonly-files
    """
    os.chmod( name, stat.S_IWRITE )
    os.remove( name )


def get_immediate_subdirectories(a_dir):
    """
        How to get all of the immediate subdirectories in Python
        https://stackoverflow.com/questions/800197/how-to-get-all-of-the-immediate-subdirectories-in-python
    """
    return [ name for name in os.listdir(a_dir) if os.path.isdir( os.path.join( a_dir, name ) ) ]


def wrap_text(text):
    return re.sub( r"(?<!\n)\n(?!\n)", " ", textwrap.dedent( text ).strip( " " ) )


def get_installed_packages(setting_name):

    if sublime:
        package_control_settings = sublime.load_settings( setting_name )
        return package_control_settings.get( "installed_packages", [] )

    else:
        raise ImportError( "You can only use the Sublime Text API inside Sublime Text." )


def unique_list_join(*lists):
    unique_list = []

    for _list in lists:

        for item in _list:

            if item not in unique_list:
                unique_list.append( item )

    return unique_list


def unique_list_append(a_list, *lists):

    for _list in lists:

        for item in _list:

            if item not in a_list:
                a_list.append( item )


def upcase_first_letter(s):
    return s[0].upper() + s[1:]


def _clean_urljoin(url):

    if url.startswith( '/' ) or url.startswith( ' ' ):
        url = url[1:]
        url = _clean_urljoin( url )

    if url.endswith( '/' ) or url.endswith( ' ' ):
        url = url[0:-1]
        url = _clean_urljoin( url )

    return url


def clean_urljoin(*urls):
    fixed_urls = []

    for url in urls:

        fixed_urls.append( _clean_urljoin(url) )

    return "/".join( fixed_urls )


def dictionary_to_string_by_line(dictionary):
    variables = \
    [
        "%-30s: %s" % ( variable_name, dictionary[variable_name] )
        for variable_name in dictionary.keys()
    ]

    return "\n\n%s" % ( "\n".join( sorted(variables) ) )


def convert_to_unix_path(relative_path):
    relative_path = relative_path.replace( "\\", "/" )

    if relative_path.startswith( "/" ):
        relative_path = relative_path[1:]

    return relative_path


def progress_info(progress):

    return "{:>05.2f}%, {:s} of {:s}".format(
            progress.progress * 100, format_time( progress.elapsed_time ), format_time( progress.time_remaining() ) )


def format_time(seconds):

    hours   = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = int(seconds % 60)

    return "%02d:%02d:%02d" % ( hours, minutes, seconds )

