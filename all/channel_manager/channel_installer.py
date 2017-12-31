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
# Channel Manager Installer, install channel packages
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
import sublime_plugin

import os
import re
import sys
import time
import shutil

import io
import json
import shlex
import threading
import configparser

g_is_running = False
g_is_package_control_installed = False

# How many packages to ignore and unignore in batch to fix the ignored packages bug error
PACKAGES_COUNT_TO_IGNORE_AHEAD = 8

CLEAN_PACKAGESMANAGER_FLAG   = 1
RESTORE_REMOVE_ORPHANED_FLAG = 2
ALL_RUNNING_CONTROL_FLAGS    = CLEAN_PACKAGESMANAGER_FLAG | RESTORE_REMOVE_ORPHANED_FLAG


from collections import OrderedDict
from estimated_time_left import sequence_timer
from estimated_time_left import progress_info
from estimated_time_left import CurrentUpdateProgress

from . import settings as g_settings

from .channel_utilities import add_item_if_not_exists
from .channel_utilities import remove_item_if_exists
from .channel_utilities import convert_to_unix_path
from .channel_utilities import wrap_text
from .channel_utilities import is_directory_empty

from .channel_utilities import get_installed_packages
from .channel_utilities import unique_list_join
from .channel_utilities import unique_list_append
from .channel_utilities import load_data_file
from .channel_utilities import write_data_file
from .channel_utilities import string_convert_list
from .channel_utilities import get_main_directory
from .channel_utilities import get_dictionary_key
from .channel_utilities import remove_if_exists
from .channel_utilities import delete_read_only_file
from .channel_utilities import _delete_read_only_file
from .channel_utilities import wrap_text
from .channel_utilities import safe_remove
from .channel_utilities import remove_only_if_exists
from .channel_utilities import InstallationCancelled
from .channel_utilities import NoPackagesAvailable
from .channel_utilities import load_repository_file
from .channel_utilities import is_channel_upgraded
from .channel_utilities import recursively_delete_empty_folders
from .channel_utilities import print_failed_repositories
from .channel_utilities import sort_dictionary
from .channel_utilities import add_path_if_not_exists
from .channel_utilities import is_dependency
from .channel_utilities import is_package_dependency
from .channel_utilities import remove_git_folder
from .channel_utilities import add_git_folder_by_file


# When there is an ImportError, means that Package Control is installed instead of PackagesManager,
# or vice-versa. Which means we cannot do nothing as this is only compatible with PackagesManager.
try:
    from package_control import cmd
    g_is_package_control_installed = True

    from package_control.package_manager import PackageManager
    from package_control.package_disabler import PackageDisabler

    from package_control.thread_progress import ThreadProgress
    from package_control.commands.satisfy_dependencies_command import SatisfyDependenciesThread
    from package_control.commands.advanced_install_package_command import AdvancedInstallPackageThread

    def silence_error_message_box(value):
        pass

except ImportError:
    from PackagesManager.packagesmanager import cmd
    from PackagesManager.packagesmanager.show_error import silence_error_message_box

    from PackagesManager.packagesmanager.package_manager import PackageManager
    from PackagesManager.packagesmanager.package_disabler import PackageDisabler

    from PackagesManager.packagesmanager.thread_progress import ThreadProgress
    from PackagesManager.packagesmanager.commands.satisfy_dependencies_command import SatisfyDependenciesThread
    from PackagesManager.packagesmanager.commands.advanced_install_package_command import AdvancedInstallPackageThread


from python_debug_tools import Debugger

# Debugger settings: 0 - disabled, 127 - enabled
log = Debugger( 127, os.path.basename( __file__ ) )

def _grade():
    return 1 & ( not IS_UPDATE_INSTALLATION )

# log( 2, "..." )
# log( 2, "..." )
# log( 2, "Debugging" )
# log( 2, "CURRENT_PACKAGE_ROOT_DIRECTORY:     " + g_settings.CURRENT_PACKAGE_ROOT_DIRECTORY )


def main(channel_settings, is_forced=False):
    """
        Before calling this installer, the `Package Control` user settings file, must have the
        Channel file set before the default channel key `channels`.

        Also the current `Package Control` cache must be cleaned, ensuring it is downloading and
        using the Channel repositories/channel list.
    """
    # We can only run this when we are using the stable version of the channel. And when there is
    # not a `.git` folder, we are running the `Development Version` of the channel.
    main_git_path = os.path.join( g_settings.CURRENT_PACKAGE_ROOT_DIRECTORY, ".git" )

    # Not attempt to run when we are running from outside a `.sublime-package` as the upgrader is
    # only available for the `Stable Version` of the channel. The `Development Version` must use
    # git itself to install or remove packages.
    if is_forced or not os.path.exists( main_git_path ) and is_channel_upgraded( channel_settings ):
        log( 1, "Entering on %s main(0)" % g_settings.CURRENT_PACKAGE_NAME )
        global g_installer_thread

        g_installer_thread = ChannelInstaller( channel_settings )
        g_installer_thread.start()


class ChannelInstaller(threading.Thread):

    def __init__(self, channel_settings):
        global IS_UPDATE_INSTALLATION

        threading.Thread.__init__(self)
        self.channelSettings = channel_settings

        self.channelName   = self.channelSettings['CHANNEL_PACKAGE_NAME']
        self.isDevelopment = self.channelSettings['INSTALLATION_TYPE'] == "development"

        self.failedRepositories       = []
        self.commandLineInterface     = cmd.Cli( None, True )
        self.uningoredPackagesToFlush = 0

        if self.channelSettings['INSTALLER_TYPE'] == 'installation':
            self.isUpdateInstallation = self.channelSettings['INSTALLATION_TYPE'] == "upgrade"
            self.setupInstaller()

        else:
            self.isUpdateInstallation = self.channelSettings['INSTALLATION_TYPE'] == "downgrade"
            self.setupUninstaller()

        IS_UPDATE_INSTALLATION = self.isUpdateInstallation
        load_installation_settings_file( self )

        if not self.isInstaller:
            self.load_package_control_settings()
            self.setup_packages_to_uninstall_last()

        self.package_manager  = PackageManager()
        self.package_disabler = PackageDisabler()

        log( 1, "INSTALLER_TYPE:            " + str( self.channelSettings['INSTALLER_TYPE'] ) )
        log( 1, "INSTALLATION_TYPE:         " + str( self.channelSettings['INSTALLATION_TYPE'] ) )
        log( 1, "self.isUpdateInstallation: " + str( self.isUpdateInstallation ) )


    def setupInstaller(self):
        self.word_prefix  = ""
        self.word_Prefix  = ""

        self.word_install = "install"
        self.word_Install = "Install"

        self.word_installed = "installed"
        self.word_Installed = "Installed"

        self.word_installer = "installer"
        self.word_Installer = "Installer"

        self.word_installation = "installation"
        self.word_Installation = "Installation"

        self.install_message    = "Select this to not install it."
        self.uninstall_message  = "Select this to install it."

        self.isInstaller       = True
        self.installationType  = "Upgrade" if self.isUpdateInstallation else "Installation"
        self.installerMessage  = "The %s was successfully installed." % self.installationType
        self.notInstallMessage = "You must install it or cancel the %s." % self.installationType
        self.setProgress       = CurrentUpdateProgress( 'Installing the %s packages...' % self.installationType )

        def packagesInformations():
            return \
            [
                [ "Cancel the Installation Process", "Select this to cancel the %s process." % self.installationType ],
                [ "Continue the Installation Process...", "Select this when you are finished selections packages." ]
            ]

        self.packagesInformations = packagesInformations


    def setupUninstaller(self):
        self.word_prefix  = "un"
        self.word_Prefix  = "Un"

        self.word_install = "uninstall"
        self.word_Install = "Uninstall"

        self.word_installed = "uninstalled"
        self.word_Installed = "Uninstalled"

        self.word_installer = "uninstaller"
        self.word_Installer = "Uninstaller"

        self.word_installation = "uninstallation"
        self.word_Installation = "Uninstallation"

        self.install_message    = "Select this to not uninstall it."
        self.uninstall_message  = "Select this to uninstall it."

        self.isInstaller       = False
        self.installationType  = "Downgrade" if self.isUpdateInstallation else "Uninstallation"
        self.installerMessage  = "The %s of %s was successfully completed." % ( self.installationType, self.channelName )
        self.notInstallMessage = "You must uninstall it or cancel the %s." % self.installationType
        self.setProgress       = CurrentUpdateProgress( '%s of Sublime Text %s packages...' % ( self.installationType, self.channelName ) )

        def packagesInformations():
            return \
            [
                [ "Cancel the %s Process" % self.installationType, "Select this to cancel the %s process." % self.installationType ],
                [ "Continue the %s Process..." % self.installationType, "Select this when you are finished selecting packages." ],
            ]

        self.packagesInformations = packagesInformations


    def load_package_control_settings(self):
        global g_package_control_settings

        # Allow to not override the Package Control file when PackagesManager does exists
        if os.path.exists( PACKAGESMANAGER ):
            g_package_control_settings = load_data_file( PACKAGESMANAGER )

        else:
            g_package_control_settings = load_data_file( PACKAGE_CONTROL )

        global g_installed_packages
        global g_remove_orphaned_backup

        g_installed_packages     = get_dictionary_key( g_package_control_settings, 'installed_packages', [] )
        g_remove_orphaned_backup = get_dictionary_key( g_package_control_settings, 'remove_orphaned', True )

        if not self.isUpdateInstallation:
            # Temporally stops Package Control from removing orphaned packages, otherwise it will scroll up
            # the uninstallation when Package Control is installed back
            g_package_control_settings['remove_orphaned'] = False
            self.save_package_control_settings()


    def setup_packages_to_uninstall_last(self):
        """
            Remove the remaining packages to be uninstalled separately on another function call.
        """
        global PACKAGES_TO_UNINSTALL_FIRST
        global PACKAGES_TO_UNINSTALL_LAST

        global PACKAGES_TO_UNINSTAL_LATER
        global PACKAGES_TO_NOT_ADD_TO_IGNORE_LIST

        PACKAGES_TO_UNINSTAL_LATER  = [ "PackagesManager", self.channelSettings['CHANNEL_PACKAGE_NAME'] ]
        PACKAGES_TO_UNINSTALL_FIRST = list( reversed( self.channelSettings['PACKAGES_TO_INSTALL_LAST'] ) )
        PACKAGES_TO_UNINSTALL_LAST  = list( reversed( self.channelSettings['PACKAGES_TO_INSTALL_FIRST'] ) )

        # We need to remove it by last, after installing Package Control back
        for package in PACKAGES_TO_UNINSTAL_LATER:

            if package in PACKAGES_TO_UNINSTALL_FIRST:
                PACKAGES_TO_UNINSTALL_FIRST.remove( package )

        PACKAGES_TO_NOT_ADD_TO_IGNORE_LIST = set( PACKAGES_TO_UNINSTAL_LATER )
        PACKAGES_TO_NOT_ADD_TO_IGNORE_LIST.add( "Default" )


    def run(self):
        """
            The installation is not complete when the user cancelled the installation process or
            there are no packages available for an upgrade.

            Python thread exit code
            https://stackoverflow.com/questions/986616/python-thread-exit-code
        """

        if is_allowed_to_run():

            if self.isInstaller:
                self.setupThread( self.installerProcedements )

            else:
                self.setupThread( self.uninstallerProcedements )

            # Progressively saves the installation data, in case the user closes Sublime Text
            self.save_default_settings()

            if not self.isUpdateInstallation:
                # Wait PackagesManager to load the found dependencies, before announcing it to the user
                sublime.set_timeout_async( self.check_installed_packages, 10000 )
                sublime.set_timeout_async( self.check_installed_packages_alert, 1000 )


    def setupThread(self, targetFunction):
        self.installerThread = threading.Thread( target=targetFunction )
        self.installerThread.start()

        ThreadProgress( self.installerThread, self.setProgress, self.installerMessage )
        self.installerThread.join()


    def installerProcedements(self):
        log( _grade(), "Entering on %s run(1)" % self.__class__.__name__ )

        self.git_executable_path = self.commandLineInterface.find_binary( "git.exe" if os.name == 'nt' else "git" )
        log( _grade(), "run, git_executable_path: " + str( self.git_executable_path ) )

        try:
            self.install_modules()

        except ( InstallationCancelled, NoPackagesAvailable ) as error:
            log( 1, str( error ) )

            # Set the flag as completed, to signalize the installation has ended
            global g_is_running
            g_is_running = False

        if not self.isUpdateInstallation:
            self.uninstall_package_control()


    def uninstallerProcedements(self):
        log( _grade(), "Entering on %s run(1)" % self.__class__.__name__ )

        try:
            packages_to_uninstall = self.get_packages_to_uninstall( self.isUpdateInstallation )

            log( _grade(), "Packages to %s: " % self.installationType + str( packages_to_uninstall ) )
            self.uninstall_packages( packages_to_uninstall )

            if not self.isUpdateInstallation:
                self.remove_channel()

                self.uninstall_files()
                self.uninstall_folders()

            self.attempt_to_uninstall_packagesmanager( packages_to_uninstall )

            if not self.isUpdateInstallation:
                self.uninstall_list_of_packages( [(self.channelSettings['CHANNEL_PACKAGE_NAME'], False)] )

        except ( InstallationCancelled, NoPackagesAvailable ) as error:
            log( 1, str( error ) )

            # Set the flag as completed, to signalize the installation has ended
            global g_is_running
            g_is_running = 0


    def install_modules(self):

        if self.isDevelopment:
            packages_to_install = self.download_not_packages_submodules()
            self.install_development_packages( packages_to_install )

        else:
            packages_to_install = self.get_stable_packages()
            self.install_stable_packages( packages_to_install )


    def get_stable_packages(self):
        """
            python ConfigParser: read configuration from string
            https://stackoverflow.com/questions/27744058/python-configparser-read-configuration-from-string
        """
        log( 2, "get_stable_packages, PACKAGES_TO_NOT_INSTALL_STABLE: " + str( self.channelSettings['PACKAGES_TO_NOT_INSTALL_STABLE'] ) )
        channel_name = self.channelSettings['CHANNEL_PACKAGE_NAME']

        current_index     = 0
        filtered_packages = []

        installed_packages = get_installed_packages( exclusion_list=[channel_name] )
        log( _grade(), "get_stable_packages, installed_packages: " + str( installed_packages ) )

        # Do not try to install this own package and the Package Control, as they are currently running
        currently_running = [ "Package Control", g_settings.CURRENT_PACKAGE_NAME, channel_name ]

        packages_tonot_install = unique_list_join \
        (
            currently_running,
            installed_packages,
            g_packages_to_uninstall,
            g_packages_not_installed if self.isUpdateInstallation else [],
            self.channelSettings['PACKAGES_TO_NOT_INSTALL_STABLE'],
            self.channelSettings['PACKAGES_TO_IGNORE_ON_DEVELOPMENT'],
        )

        packages_to_install    = {}
        install_exclusively    = self.channelSettings['PACKAGES_TO_INSTALL_EXCLUSIVELY']
        is_exclusively_install = not not len( install_exclusively )

        repositories_loaded = load_repository_file( self.channelSettings['CHANNEL_REPOSITORY_FILE'], {} )
        log( _grade(), "get_stable_packages, packages_tonot_install: " + str( packages_tonot_install ) )

        if is_exclusively_install:
            log( _grade(), "Performing exclusively installation of the packages: " + str( install_exclusively ) )

            for package_name in repositories_loaded:

                if package_name in install_exclusively:
                    packages_to_install[package_name] = repositories_loaded[package_name]

        else:
            packages_to_install = repositories_loaded

        for package_name in packages_to_install:
            log( 2, "get_stable_packages, package_name: " + package_name )

            # # For quick testing
            # current_index += 1
            # if current_index > 7:
            #     break

            if package_name not in packages_tonot_install \
                    and not is_dependency( package_name, packages_to_install ):

                filtered_packages.append( package_name )

            # When installing the channel, we must mark the packages already installed as packages which
            # where not installed, so they are not uninstalled when the channel is uninstalled.
            if not self.isUpdateInstallation \
                    and package_name in installed_packages:

                g_packages_not_installed.append( package_name )

        # return \
        # [
        #     ('Active View Jump Back', False),
        #     ('amxmodx', False),
        #     ('Amxx Pawn', False),
        #     ('Clear Cursors Carets', False),
        #     ('Indent and braces', False),
        #     ('Invert Selection', False),
        #     ('PackagesManager', False),
        #     ('Toggle Words', False),
        #     # ('BBCode', False),
        #     ('DocBlockr', False),
        #     ('Gist', False),
        #     ('FileManager', False),
        #     ('FuzzyFileNav', False),
        #     ('ExportHtml', False),
        #     ('ExtendedTabSwitcher', False),
        #     ('BufferScroll', False),
        #     ('ChannelRepositoryTools', False),
        #     ('Better CoffeeScript', False),
        # ]

        if len( filtered_packages ) < 1:
            raise NoPackagesAvailable( "There are 0 packages available to install!" )

        if self.isUpdateInstallation:
            log( 1, "New packages packages to install found... " + str( filtered_packages ) )

        return filtered_packages


    def install_stable_packages(self, packages_names):
        """
            python multithreading wait till all threads finished
            https://stackoverflow.com/questions/11968689/python-multithreading-wait-till-all-threads-finished

            There is a bug with the AdvancedInstallPackageThread thread which trigger several errors of:

            "It appears a package is trying to ignore itself, causing a loop.
            Please resolve by removing the offending ignored_packages setting."

            When trying to install several package at once, then here I am installing them one by one.
        """
        self.set_default_settings( packages_names )
        log( 2, "install_stable_packages, packages_names: " + str( packages_names ) )

        # Package Control: Advanced Install Package
        # https://github.com/wbond/package_control/issues/1191
        # thread = AdvancedInstallPackageThread( packages_names )
        # thread.start()
        # thread.join()

        current_index      = 0
        git_packages_count = len( packages_names )

        for package_name, pi in sequence_timer( packages_names, info_frequency=0 ):
            current_index += 1
            progress = progress_info( pi, self.setProgress )

            # # For quick testing
            # if current_index > 3:
            #     break

            log.insert_empty_line()
            log.insert_empty_line()

            log( 1, "%s Installing %d of %d: %s" % ( progress, current_index, git_packages_count, str( package_name ) ) )
            self.ignore_next_packages( package_name, packages_names )

            if self.package_manager.install_package( package_name, False ) is False:
                log( 1, "Error: Failed to install the repository `%s`!" % package_name )
                self.failedRepositories.append( package_name )

            else:
                self.add_package_to_installation_list( package_name )

            self.accumulative_unignore_user_packages( package_name )

        self.accumulative_unignore_user_packages( flush_everything=True )


    def download_not_packages_submodules(self):
        log( 1, "download_not_packages_submodules" )

        root = self.channelSettings['CHANNEL_ROOT_DIRECTORY']
        self.clone_sublime_text_channel()

        gitFilePath    = os.path.join( root, '.gitmodules' )
        gitModulesFile = configparser.RawConfigParser()

        current_index = 0
        gitModulesFile.read( gitFilePath )

        for section in gitModulesFile.sections():
            url  = gitModulesFile.get( section, "url" )
            path = gitModulesFile.get( section, "path" )

            # # For quick testing
            # current_index += 1
            # if current_index > 3:
            #     break

            if 'Packages' != path[0:8]:
                package_name            = os.path.basename( path )
                submodule_absolute_path = os.path.join( root, path )

                if is_directory_empty( submodule_absolute_path ):
                    log.insert_empty_line()
                    log.insert_empty_line()
                    log( 1, "Installing: %s" % ( str( url ) ) )

                    command = shlex.split( '"%s" clone "%s" "%s"' % ( git_executable_path, url, path ) )
                    output  = str( commandLineInterface.execute( command, cwd=root ) )

                    self.add_folders_and_files_for_removal( submodule_absolute_path, path )
                    log( 1, "download_not_packages_submodules, output: " + str( output ) )

                    # Progressively saves the installation data, in case the user closes Sublime Text
                    self.save_default_settings()

        return self.get_development_packages()


    def get_development_packages(self):
        development_ignored = self.channelSettings['PACKAGES_TO_NOT_INSTALL_DEVELOPMENT']
        log( 2, "install_submodules_packages, PACKAGES_TO_NOT_INSTALL_DEVELOPMENT: " + str( development_ignored ) )

        gitFilePath    = os.path.join( self.channelSettings['CHANNEL_ROOT_DIRECTORY'], '.gitmodules' )
        gitModulesFile = configparser.RawConfigParser()

        current_index      = 0
        installed_packages = get_installed_packages( exclusion_list=[self.channelName] )

        packages_tonot_install = unique_list_join( development_ignored, installed_packages )
        log( 2, "get_development_packages, packages_tonot_install: " + str( packages_tonot_install ) )

        packages = []
        gitModulesFile.read( gitFilePath )

        for section in gitModulesFile.sections():
            # # For quick testing
            # current_index += 1
            # if current_index > 3:
            #     break

            url  = gitModulesFile.get( section, "url" )
            path = gitModulesFile.get( section, "path" )

            log( 2, "get_development_packages, path: " + path )

            if 'Packages' == path[0:8]:
                package_name = os.path.basename( path )

                if package_name not in packages_tonot_install :
                    packages.append( ( package_name, url, path ) )

        return \
        [
            ('Active View Jump Back', 'https://github.com/evandrocoan/SublimeActiveViewJumpBack', 'Packages/Active View Jump Back'),
            # ('amxmodx', 'https://github.com/evandrocoan/SublimeAMXX_Editor', 'Packages/amxmodx'),
            # ('All Autocomplete', 'https://github.com/evandrocoan/SublimeAllAutocomplete', 'Packages/All Autocomplete'),
            # ('Amxx Pawn', 'https://github.com/evandrocoan/SublimeAmxxPawn', 'Packages/Amxx Pawn'),
            # ('Clear Cursors Carets', 'https://github.com/evandrocoan/ClearCursorsCarets', 'Packages/Clear Cursors Carets'),
            # ('Notepad++ Color Scheme', 'https://github.com/evandrocoan/SublimeNotepadPlusPlusTheme', 'Packages/Notepad++ Color Scheme'),
            ('PackagesManager', 'https://github.com/evandrocoan/package_control', 'Packages/PackagesManager'),
            ('Toggle Words', 'https://github.com/evandrocoan/ToggleWords', 'Packages/Toggle Words'),
            ('Default', 'https://github.com/evandrocoan/SublimeDefault', 'Packages/Default'),
            ('User', 'https://github.com/evandrocoan/User', 'Packages/User'),
        ]

        return packages


    def clone_sublime_text_channel(self):
        """
            Clone the main repository as `https://github.com/evandrocoan/SublimeTextStudio` and install
            it on the Sublime Text Data folder.
        """
        root = self.channelSettings['CHANNEL_ROOT_DIRECTORY']
        main_git_folder = os.path.join( root, ".git" )

        if os.path.exists( main_git_folder ):
            log.insert_empty_line()
            log.insert_empty_line()

            log( 1, "Error: The folder '%s' already exists.\nYou already has some custom channel git installation." % main_git_folder )
            log.insert_empty_line()

        else:
            root = self.channelSettings['CHANNEL_ROOT_DIRECTORY']
            temp = self.channelSettings['TEMPORARY_FOLDER_TO_USE']

            channel_temporary_folder = os.path.join( root, temp )
            self.download_main_repository( root, temp )

            files, folders = self.copy_overrides( channel_temporary_folder, root )
            shutil.rmtree( channel_temporary_folder, onerror=_delete_read_only_file )

            unique_list_append( g_files_to_uninstall, files )
            unique_list_append( g_folders_to_uninstall, folders )

            # Progressively saves the installation data, in case the user closes Sublime Text
            self.save_default_settings()


    def download_main_repository(self, root, temp):
        log( 1, "download_main_repository..." )
        url = self.channelSettings['CHANNEL_ROOT_URL']

        log.insert_empty_line()
        log.insert_empty_line()

        log( 1, "Installing: %s" % ( str( self.channelSettings['CHANNEL_ROOT_URL'] ) ) )
        self.download_repository_to_folder( url, root, temp )

        # Delete the empty folders created by git while cloning the main repository
        channel_temporary_folder = os.path.join( root, temp )
        recursively_delete_empty_folders( channel_temporary_folder )


    def download_repository_to_folder(self, url, root, temp ):
        channel_temporary_folder = os.path.join( root, temp )

        if os.path.isdir( channel_temporary_folder ):
            shutil.rmtree( channel_temporary_folder, onerror=_delete_read_only_file )

        command = shlex.split( '"%s" clone "%s" "%s"' % ( self.git_executable_path, url, temp ) )
        output  = str( self.commandLineInterface.execute( command, cwd=root ) )

        log( 1, "download_repository_to_folder, output: " + str( output ) )


    def install_development_packages(self, packages_infos):
        root = self.channelSettings['CHANNEL_ROOT_DIRECTORY']
        temp = self.channelSettings['TEMPORARY_FOLDER_TO_USE']

        packages_names = [ package_info[0] for package_info in packages_infos ]
        channel_temporary_folder = os.path.join( root, temp )

        self.set_default_settings( packages_names, packages_infos )
        log( 2, "install_development_packages, packages_infos: " + str( packages_infos ) )

        current_index      = 0
        git_packages_count = len( packages_infos )

        for package_info, pi in sequence_timer( packages_infos, info_frequency=0 ):
            current_index += 1
            package_name, url, path = package_info

            progress = progress_info( pi, self.setProgress )
            submodule_absolute_path = os.path.join( root, path )

            # # For quick testing
            # if current_index > 3:
            #     break

            log.insert_empty_line()
            log.insert_empty_line()

            log( 1, "%s Installing %d of %d: %s" % ( progress, current_index, git_packages_count, str( package_name ) ) )
            self.ignore_next_packages( package_name, packages_names )

            if os.path.exists( submodule_absolute_path ):

                # Add the missing packages file into the existent packages folder, including the `.git` folder.
                if self.package_manager.backup_package_dir( package_name ):
                    self.download_repository_to_folder( url, root, temp )
                    self.copy_overrides( channel_temporary_folder, submodule_absolute_path, move_files=True, is_to_replace=False )

                else:
                    self.failedRepositories.append( package_name )

                    log( 1, "Error: Failed to backup and install the repository `%s`!" % package_name )
                    continue

            else:
                command = shlex.split( '"%s" clone --recursive "%s" "%s"' % ( self.git_executable_path, url, path) )
                result  = self.commandLineInterface.execute( command, cwd=root )

                if result is False:
                    self.failedRepositories.append( package_name )
                    log( 1, "Error: Failed to download the repository `%s`!" % package_name )
                    continue

            command = shlex.split( '"%s" checkout master' % ( self.git_executable_path ) )
            output  = str( result ) + "\n" + str( self.commandLineInterface.execute( command, cwd=os.path.join( root, path ) ) )

            log( 1, "install_development_packages, output: " + str( output ) )

            self.add_package_to_installation_list( package_name )
            self.accumulative_unignore_user_packages( package_name )

        self.accumulative_unignore_user_packages( flush_everything=True )

        # Clean the temporary folder after the process has ended
        shutil.rmtree( channel_temporary_folder, onerror=_delete_read_only_file )


    def get_packages_to_uninstall(self, is_downgrade):
        filtered_packages     = []
        last_packages         = []
        packages_to_uninstall = get_dictionary_key( g_channelDetails, 'packages_to_uninstall', [] )

        if is_downgrade:
            packages_to_not_remove = set()
            repositories_loaded    = load_repository_file( self.channelSettings['CHANNEL_REPOSITORY_FILE'], {} )

            install_exclusively    = self.channelSettings['PACKAGES_TO_INSTALL_EXCLUSIVELY']
            is_exclusively_install = not not len( install_exclusively )

            if is_exclusively_install:

                for package_name in repositories_loaded:

                    if package_name in install_exclusively:
                        packages_to_not_remove.add( package_name )

            packages_to_uninstall = set( packages_to_uninstall + g_packages_not_installed ) - packages_to_not_remove

        for package_name in PACKAGES_TO_UNINSTALL_FIRST:

            # Only merges the packages which are actually being uninstalled
            if package_name in packages_to_uninstall:
                filtered_packages.append( package_name )

        for package_name in PACKAGES_TO_UNINSTALL_LAST:

            # Only merges the packages which are actually being uninstalled
            if package_name in packages_to_uninstall:
                last_packages.append( package_name )
                packages_to_uninstall.remove( package_name )

        # Add the remaining packages after the packages to install first
        for package_name in packages_to_uninstall:

            if package_name not in filtered_packages:
                filtered_packages.append( package_name )

        # Finally add the last packages to the full list
        unique_list_append( filtered_packages, last_packages )

        if is_downgrade:

            # Allow to uninstall only the channel package when there is no other packages installed
            if len( filtered_packages ) < 1:
                raise NoPackagesAvailable( "There are 0 packages available to uninstall!" )

            log( 1, "New packages packages to uninstall found... " + str( filtered_packages ) )

        return filtered_packages


    def uninstall_packages(self, packages_names):
        self.ask_user_for_which_packages_to_install( packages_names )
        all_packages, dependencies = self.get_installed_repositories()

        current_index  = 0
        packages_count = len( packages_names )

        for package_name, pi in sequence_timer( packages_names, info_frequency=0 ):
            current_index += 1
            progress       = progress_info( pi, self.setProgress )
            is_dependency  = is_package_dependency( package_name, dependencies, all_packages )

            log.insert_empty_line()
            log.insert_empty_line()

            log( 1, "%s %s of %d of %d: %s (%s)" % ( progress, self.installationType,
                    current_index, packages_count, str( package_name ), str( is_dependency ) ) )

            silence_error_message_box( 61.0 )
            self.ignore_next_packages( package_name, packages_names )

            if package_name == "Default":
                self.uninstall_default_package()
                continue

            if package_name in PACKAGES_TO_UNINSTAL_LATER:
                log( 1, "Skipping the %s of `%s`..." % ( self.installationType, package_name ) )
                log( 1, "This package will be handled later." )
                continue

            if is_dependency:
                log( 1, "Skipping the dependency as they are automatically uninstalled..." )
                continue

            if self.package_manager.remove_package( package_name, is_dependency ) is False:
                log( 1, "Error: Failed to uninstall the repository `%s`!" % package_name )
                self.failedRepositories.append( package_name )

            else:
                self.remove_packages_from_list( package_name )

            self.accumulative_unignore_user_packages( package_name )

        self.accumulative_unignore_user_packages( flush_everything=True )


    def get_installed_repositories(self):
        dependencies = None
        all_packages = None

        if g_is_package_control_installed:
            _dependencies = self.package_manager.list_dependencies()
            dependencies  = set( _dependencies )
            all_packages  = set( _dependencies + get_installed_packages( list_default_packages=True ) )

        else:
            dependencies = set( self.package_manager.list_dependencies() )
            all_packages = set( self.package_manager.list_packages( list_everything=True ) )

        return all_packages, dependencies


    def uninstall_default_package(self):
        log( 1, "%s of `Default Package` files..." % self.installationType )

        files_installed       = get_dictionary_key( g_channelDetails, 'default_package_files', [] )
        default_packages_path = os.path.join( self.channelSettings['CHANNEL_ROOT_DIRECTORY'], "Packages", "Default" )

        for file in files_installed:
            file_path = os.path.join( default_packages_path, file )
            remove_only_if_exists( file_path )

        default_git_folder = os.path.join( default_packages_path, ".git" )
        remove_git_folder( default_git_folder, default_packages_path )


    def remove_channel(self):
        channels = get_dictionary_key( g_package_control_settings, "channels", [] )

        while self.channelSettings['CHANNEL_FILE_URL'] in channels:
            log( 1, "Removing %s channel from Package Control settings: %s" % ( self.channelSettings['CHANNEL_PACKAGE_NAME'], str( channels ) ) )
            channels.remove( self.channelSettings['CHANNEL_FILE_URL'] )

        g_package_control_settings['channels'] = channels
        self.save_package_control_settings()


    def save_package_control_settings(self):
        global g_package_control_settings
        g_installed_packages.sort()

        g_package_control_settings['installed_packages'] = g_installed_packages
        g_package_control_settings = sort_dictionary( g_package_control_settings )

        write_data_file( PACKAGE_CONTROL, g_package_control_settings )


    def remove_packages_from_list(self, package_name):
        remove_if_exists( g_installed_packages, package_name )
        remove_if_exists( g_packages_to_uninstall, package_name )

        # Progressively saves the installation data, in case the user closes Sublime Text
        self.save_default_settings()
        self.save_package_control_settings()


    def uninstall_files(self):
        git_folders = []

        log.insert_empty_line()
        log.insert_empty_line()
        log( 1, "%s of added files: %s" % ( self.installationType, str( g_files_to_uninstall ) ) )

        for file in g_files_to_uninstall:
            log( 1, "Uninstalling file: %s" % str( file ) )
            file_absolute_path = os.path.join( self.channelSettings['CHANNEL_ROOT_DIRECTORY'], file )

            safe_remove( file_absolute_path )
            add_git_folder_by_file( file, git_folders )

        del g_files_to_uninstall[:]
        log( 1, "Removing git_folders..." )

        for git_folder in git_folders:
            remove_git_folder( git_folder )

        # Progressively saves the installation data, in case the user closes Sublime Text
        self.save_default_settings()


    def uninstall_folders(self):
        log.insert_empty_line()
        log.insert_empty_line()
        log( 1, "%s of added folders: %s" % ( self.installationType, str( g_files_to_uninstall ) ) )

        for folder in reversed( g_files_to_uninstall ):
            folders_not_empty = []
            log( 1, "Uninstalling folder: %s" % str( folder ) )

            folder_absolute_path = os.path.join( self.channelSettings['CHANNEL_ROOT_DIRECTORY'], folder )
            recursively_delete_empty_folders( folder_absolute_path, folders_not_empty )

        for folder in g_files_to_uninstall:
            folders_not_empty = []
            log( 1, "Uninstalling folder: %s" % str( folder ) )

            folder_absolute_path = os.path.join( self.channelSettings['CHANNEL_ROOT_DIRECTORY'], folder )
            recursively_delete_empty_folders( folder_absolute_path, folders_not_empty )

        for folder in g_files_to_uninstall:
            folders_not_empty = []
            log( 1, "Uninstalling folder: %s" % str( folder ) )

            folder_absolute_path = os.path.join( self.channelSettings['CHANNEL_ROOT_DIRECTORY'], folder )
            recursively_delete_empty_folders( folder_absolute_path, folders_not_empty )

            if len( folders_not_empty ) > 0:
                log( 1, "The installed folder `%s` could not be removed because is it not empty." % folder_absolute_path )
                log( 1, "Its files contents are: " + str( os.listdir( folder_absolute_path ) ) )

        del g_files_to_uninstall[:]

        # Progressively saves the installation data, in case the user closes Sublime Text
        self.save_default_settings()


    def uninstall_package_control(self):
        """
            Uninstals package control only if PackagesManager was installed, otherwise the user will end
            up with no package manager.
        """
        log( 2, "uninstall_package_control, g_packages_to_uninstall: " + str( g_packages_to_uninstall ) )

        # Only uninstall it, when `PackagesManager` was also installed
        if "PackagesManager" in g_packages_to_uninstall:
            # Sublime Text is waiting the current thread to finish before loading the just installed
            # PackagesManager, therefore run a new thread delayed which finishes the job
            sublime.set_timeout_async( self.complete_package_control_uninstallation, 2000 )

        else:
            satisfy_dependencies( SatisfyDependenciesThread, self.package_manager )
            log( 1, "Warning: PackagesManager is was not installed on the system!" )

            # Clean right away the PackagesManager successful flag, was it was not installed
            global g_is_running
            g_is_running = False


    def complete_package_control_uninstallation(self, maximum_attempts=3):
        log.insert_empty_line()
        log.insert_empty_line()
        log( 1, "Finishing Package Control Uninstallation... maximum_attempts: " + str( maximum_attempts ) )

        # Import the recent installed PackagesManager
        try:
            from PackagesManager.packagesmanager.show_error import silence_error_message_box
            from PackagesManager.packagesmanager.package_manager import PackageManager
            from PackagesManager.packagesmanager.package_disabler import PackageDisabler
            from PackagesManager.packagesmanager.commands.satisfy_dependencies_command import SatisfyDependenciesThread

        except ImportError:

            if maximum_attempts > 0:
                maximum_attempts -= 1

                sublime.set_timeout_async( lambda: self.complete_package_control_uninstallation( maximum_attempts ), 2000 )
                return

            else:
                log( 1, "Error! Could not complete the Package Control uninstalling, missing import for `PackagesManager`." )

        silence_error_message_box( 300.0 )
        self.delete_package_control_settings( SatisfyDependenciesThread )

        # Replace the Package Control installers by the PackagesManager ones
        self.package_manager  = PackageManager()
        self.package_disabler = PackageDisabler()

        packages_to_remove = [ ("Package Control", False), ("0_package_control_loader", None) ]
        packages_names     = [ package_name[0] for package_name in packages_to_remove ]

        for package_name, is_dependency in packages_to_remove:
            log.insert_empty_line()
            log.insert_empty_line()

            log( 1, "Uninstalling: %s..." % str( package_name ) )
            self.ignore_next_packages( package_name, packages_names )
            self.package_manager.remove_package( package_name, is_dependency )

            if package_name == "0_package_control_loader":
                self.remove_0_package_dependency_loader( "0_package_control_loader" )

            self.accumulative_unignore_user_packages( package_name )

        self.accumulative_unignore_user_packages( flush_everything=True )


    def delete_package_control_settings(self, SatisfyDependenciesThread, maximum_attempts=3):
        """
            Clean it a few times because Package Control is kinda running and still flushing stuff down
            to its settings file.
        """
        log( 1, "Calling delete_package_control_settings..." )
        maximum_attempts -= 1

        clean_settings = {}
        clean_settings['bootstrapped']    = False
        clean_settings['remove_orphaned'] = False

        if "remove_orphaned_backup" in g_package_control_settings:
            clean_settings['remove_orphaned_backup'] = get_dictionary_key( g_package_control_settings, 'remove_orphaned_backup', True )

        else:
            clean_settings['remove_orphaned_backup'] = get_dictionary_key( g_package_control_settings, 'remove_orphaned', True )

        clean_settings = sort_dictionary( clean_settings )
        write_data_file( PACKAGE_CONTROL, clean_settings )

        if maximum_attempts > 0:
            sublime.set_timeout_async( lambda: self.delete_package_control_settings( SatisfyDependenciesThread, maximum_attempts ), 2000 )
            return

        satisfy_dependencies( SatisfyDependenciesThread, self.package_manager )

        # Set the flag as completed, to signalize the this part of the installation was successful
        global g_is_running
        g_is_running = False


    def attempt_to_uninstall_packagesmanager(self, packages_to_uninstall):

        if "PackagesManager" in packages_to_uninstall:
            installed_packages = self.package_manager.list_packages()

            if "Package Control" not in installed_packages:
                self.install_package_control()

            self.uninstall_packagesmanger( installed_packages )
            self.restore_remove_orphaned_setting()

        else:
            # Clean right away the PackagesManager successful flag, was it was not installed
            global g_is_running
            g_is_running &= ~CLEAN_PACKAGESMANAGER_FLAG


    def install_package_control(self):
        package_name = "Package Control"
        log.insert_empty_line()
        log.insert_empty_line()

        log( 1, "Installing: %s" % str( package_name ) )
        self.ignore_next_packages( package_name, [package_name] )

        self.package_manager.install_package( package_name, False )
        self.accumulative_unignore_user_packages( flush_everything=True )


    def uninstall_packagesmanger(self, installed_packages):
        """
            Uninstals PackagesManager only if Control was installed, otherwise the user will end up with
            no package manager.
        """

        # Only uninstall them when they were installed
        if "PackagesManager" in installed_packages:
            log.insert_empty_line()
            log.insert_empty_line()

            log( 1, "Finishing PackagesManager %s..." % self.installationType )
            self.ignore_next_packages( "PackagesManager", ["PackagesManager"] )

            self.uninstall_list_of_packages( [("PackagesManager", False), ("0_packagesmanager_loader", None)] )
            self.remove_0_package_dependency_loader( "0_packagesmanager_loader" )

            self.clean_packagesmanager_settings()
            self.accumulative_unignore_user_packages( flush_everything=True )


    def uninstall_list_of_packages(self, packages_infos):
        """
            By last uninstall itself `self.channelSettings['CHANNEL_PACKAGE_NAME']` and let the package be
            unloaded by Sublime Text
        """
        log( 1, "uninstall_list_of_packages, %s... " % self.installationType + str( packages_infos ) )
        packages_names = [ package_name for package_name, _ in packages_infos ]

        for package_name, is_dependency in packages_infos:
            log.insert_empty_line()
            log.insert_empty_line()

            log( 1, "%s of: %s..." % ( self.installationType, str( package_name ) ) )

            silence_error_message_box( 62.0 )
            self.ignore_next_packages( package_name, packages_names )

            if self.package_manager.remove_package( package_name, is_dependency ) is False:
                log( 1, "Error: Failed to uninstall the repository `%s`!" % package_name )
                self.failedRepositories.append( package_name )

            else:
                self.remove_packages_from_list( package_name )

            self.accumulative_unignore_user_packages( package_name )

        self.accumulative_unignore_user_packages( flush_everything=True )


    def remove_0_package_dependency_loader(self, loader_name):
        """
            Most times the 0_packagesmanager_loader is not being deleted/removed, then try again.
        """
        packagesmanager_loader_path     = os.path.join(
                self.channelSettings['CHANNEL_ROOT_DIRECTORY'], "Installed Packages", "%s.sublime-package" % loader_name )

        packagesmanager_loader_path_new = os.path.join(
                self.channelSettings['CHANNEL_ROOT_DIRECTORY'], "Installed Packages", "%s.sublime-package-new" % loader_name )

        remove_only_if_exists( packagesmanager_loader_path )
        remove_only_if_exists( packagesmanager_loader_path_new )


    def clean_packagesmanager_settings(self, maximum_attempts=3):
        """
            Clean it a few times because PackagesManager is kinda running and still flushing stuff down
            to its settings file.
        """
        log( 1, "Finishing PackagesManager %s... maximum_attempts: " % self.installationType + str( maximum_attempts ) )

        if maximum_attempts == 3:
            write_data_file( PACKAGESMANAGER, {} )

        # If we do not write nothing to package_control file, Sublime Text will create another
        remove_only_if_exists( PACKAGESMANAGER )
        maximum_attempts -= 1

        if maximum_attempts > 0:
            sublime.set_timeout_async( lambda: self.clean_packagesmanager_settings( maximum_attempts ), 2000 )
            return

        # Set the flag as completed, to signalize the this part of the installation was successful
        global g_is_running
        g_is_running &= ~CLEAN_PACKAGESMANAGER_FLAG


    def restore_remove_orphaned_setting(self):

        if g_remove_orphaned_backup:
            # By default, it is already True on `Package Control.sublime-settings`, so just remove it
            del g_package_control_settings['remove_orphaned']

        else:
            g_package_control_settings['remove_orphaned'] = g_remove_orphaned_backup

        self.save_package_control_settings()

        # Set the flag as completed, to signalize the this part of the installation was successful
        global g_is_running
        g_is_running &= ~RESTORE_REMOVE_ORPHANED_FLAG


    def save_default_settings(self):
        """
            When uninstalling this channel we can only remove our packages, keeping the user's original
            ignored packages intact.
        """
        # https://stackoverflow.com/questions/9264763/unboundlocalerror-in-python
        # UnboundLocalError in Python
        global g_channelDetails

        if 'Default' in g_packages_to_uninstall:
            g_channelDetails['default_package_files'] = self.channelSettings['DEFAULT_PACKAGE_FILES']

        g_packages_to_uninstall.sort()
        g_packages_to_unignore.sort()
        g_files_to_uninstall.sort()
        g_folders_to_uninstall.sort()
        g_next_packages_to_ignore.sort()
        g_packages_not_installed.sort()

        # `packages_to_uninstall` and `packages_to_unignore` are to uninstall and unignore they when uninstalling the channel
        g_channelDetails['packages_to_uninstall']   = g_packages_to_uninstall
        g_channelDetails['packages_to_unignore']    = g_packages_to_unignore
        g_channelDetails['files_to_uninstall']      = g_files_to_uninstall
        g_channelDetails['folders_to_uninstall']    = g_folders_to_uninstall
        g_channelDetails['next_packages_to_ignore'] = g_next_packages_to_ignore
        g_channelDetails['packages_not_installed']  = g_packages_not_installed

        g_channelDetails['installation_type'] = g_installation_type
        g_channelDetails = sort_dictionary( g_channelDetails )

        # log( 1, "self.save_default_settings, g_channelDetails: " + json.dumps( g_channelDetails, indent=4 ) )
        write_data_file( self.channelSettings['CHANNEL_INSTALLATION_DETAILS'], g_channelDetails )


    def set_default_settings(self, packages_names, packages_infos=[]):
        """
            Set some package to be enabled at last due their settings being dependent on other packages
            which need to be installed first.

            This also disables all development disabled packages, when installing the development
            version. It sets the current user's `ignored_packages` settings including all packages
            already disabled and the new packages to be installed and must be disabled before attempting
            to install them.
        """
        self.set_first_and_last_packages_to_install( packages_names, packages_infos )
        self.ask_user_for_which_packages_to_install( packages_names, packages_infos )

        if "PackagesManager" in packages_names:
            self.sync_package_control_and_manager()

        else:
            global g_package_control_settings
            g_package_control_settings = None

        # The development version does not need to ignore all installed packages before starting the
        # installation process as it is not affected by the Sublime Text bug.
        if self.isDevelopment:
            self.set_development_ignored_packages( packages_names )


    def set_development_ignored_packages(self, packages_to_install):

        for package_name in self.channelSettings['PACKAGES_TO_IGNORE_ON_DEVELOPMENT']:

            # Only ignore the packages which are being installed
            if package_name in packages_to_install and package_name not in g_default_ignored_packages:
                g_default_ignored_packages.append( package_name )
                add_item_if_not_exists( g_packages_to_unignore, package_name )

        self.setup_packages_ignored_list( g_default_ignored_packages )


    def sync_package_control_and_manager(self):
        """
            When the installation is going on the PackagesManager will be installed. If the user restart
            Sublime Text after doing it, on the next time Sublime Text starts, the Package Control and
            the PackagesManager will kill each other and probably end up uninstalling all the packages
            installed.

            This happens due their configurations files list different sets of packages. So to fix this
            we need to keep both files synced while the installation process is going on.
        """
        log( 1, "Calling sync_package_control_and_manager..." )
        global g_package_control_settings
        g_package_control_settings = load_data_file( PACKAGE_CONTROL )

        log( 2, "sync_package_control_and_manager, package_control: " + str( g_package_control_settings ) )
        self.ensure_installed_packages_name( g_package_control_settings )

        packagesmanager = os.path.join( self.channelSettings['USER_FOLDER_PATH'], g_packagesmanager_name )
        write_data_file( packagesmanager, g_package_control_settings )


    def ensure_installed_packages_name(self, package_control_settings):
        """
            Ensure the installed packages names are on the settings files.
        """

        if "installed_packages" in package_control_settings:
            installed_packages = get_dictionary_key( package_control_settings, 'installed_packages', [] )

            remove_item_if_exists( installed_packages, "Package Control" )

            add_item_if_not_exists( installed_packages, "PackagesManager" )
            add_item_if_not_exists( installed_packages, self.channelSettings['CHANNEL_PACKAGE_NAME'] )

        else:
            channel_name = self.channelSettings['CHANNEL_PACKAGE_NAME']
            package_control_settings['installed_packages'] = [ "PackagesManager", channel_name ]

        # The `remove_orphaned_backup` is used to save the default user value for the overridden key
        # `remove_orphaned` by the `PackagesManager` when configuring
        if "remove_orphaned_backup" in package_control_settings:
            package_control_settings['remove_orphaned'] = package_control_settings['remove_orphaned_backup']
            del package_control_settings['remove_orphaned_backup']


    def set_first_and_last_packages_to_install(self, packages_names, packages_infos=[]):
        """
            Set the packages to be installed first and last. The `self.channelSettings['PACKAGES_TO_INSTALL_LAST']`
            has priority when some package is on both lists.
        """
        self.set_first_packages_to_install( packages_names, packages_infos )
        last_packages = {}

        if len( packages_infos ):

            for package_info in packages_infos:

                if package_info[0] in self.channelSettings['PACKAGES_TO_INSTALL_LAST']:
                    last_packages[package_info[0]] = package_info

                    packages_infos.remove(package_info)
                    packages_names.remove(package_info[0])

        else:

            for package_name in packages_names:

                if package_name in self.channelSettings['PACKAGES_TO_INSTALL_LAST']:
                    last_packages[package_name] = package_name

                    packages_names.remove( package_name )

        # Readds the packages into the list accordingly to their respective ordering
        for package_name in self.channelSettings['PACKAGES_TO_INSTALL_LAST']:

            if package_name in last_packages:

                if len( packages_infos ):
                    packages_infos.append( last_packages[package_name] )
                    packages_names.append( last_packages[package_name][0] )

                else:
                    packages_names.append( last_packages[package_name] )


    def set_first_packages_to_install(self, packages_names, packages_infos=[]):
        first_packages = {}

        if len( packages_infos ):

            for package_info in packages_infos:

                if package_info[0] in self.channelSettings['PACKAGES_TO_INSTALL_FIRST']:
                    first_packages[package_info[0]] = package_info

                    packages_infos.remove(package_info)
                    packages_names.remove(package_info[0])

        else:

            for package_name in packages_names:

                if package_name in self.channelSettings['PACKAGES_TO_INSTALL_FIRST']:
                    first_packages[package_name] = package_name

                    packages_names.remove( package_name )

        # Readds the packages into the list accordingly to their respective ordering
        for package_name in reversed( self.channelSettings['PACKAGES_TO_INSTALL_FIRST'] ):

            if package_name in first_packages:

                if len( packages_infos ):
                    packages_infos.insert( 0, first_packages[package_name] )
                    packages_names.insert( 0, first_packages[package_name][0] )

                else:
                    packages_names.insert( 0, first_packages[package_name] )


    def ignore_next_packages(self, package_name, packages_list):
        """
            There is a bug with the uninstalling several packages, which trigger several errors of:

            "It appears a package is trying to ignore itself, causing a loop.
            Please resolve by removing the offending ignored_packages setting."

            When trying to uninstall several package at once, then here I am ignoring them all at once.

            Package Control: Advanced Install Package
            https://github.com/wbond/package_control/issues/1191

            This fixes it by ignoring several next packages, then later unignoring them after uninstalled.
        """

        if self.uningoredPackagesToFlush < 1:
            global g_next_packages_to_ignore

            last_ignored_packages     = packages_list.index( package_name )
            g_next_packages_to_ignore = packages_list[last_ignored_packages : last_ignored_packages+PACKAGES_COUNT_TO_IGNORE_AHEAD+1]

            # We never can ignore the Default package, otherwise several errors/anomalies show up
            if "Default" in g_next_packages_to_ignore:
                g_next_packages_to_ignore.remove( "Default" )

            g_next_packages_to_ignore.sort()
            log( 1, "Adding %d packages to the `ignored_packages` setting list..." % len( g_next_packages_to_ignore ) )
            log( 1, "g_next_packages_to_ignore:  " + str( g_next_packages_to_ignore ) )

            # If the package is already on the users' `ignored_packages` settings, it means either that
            # the package was disabled by the user or the package is one of the development disabled
            # packages. Therefore we must not unignore it later when unignoring them.
            for package_name in list( g_next_packages_to_ignore ):

                if package_name in g_default_ignored_packages:
                    g_next_packages_to_ignore.remove( package_name )

            # This adds them to the `in_process` list on the Package Control.sublime-settings file
            self.package_disabler.disable_packages( g_next_packages_to_ignore, "install" if self.isInstaller else "remove" )
            time.sleep( 1.7 )

            # Let the packages be unloaded by Sublime Text while ensuring anyone is putting them back in
            self.setup_packages_ignored_list( g_next_packages_to_ignore )


    def accumulative_unignore_user_packages(self, package_name="", flush_everything=False):
        """
            Flush off the remaining `next packages to ignore` appended. There is a bug with the
            uninstalling several packages, which trigger several errors of:

            "It appears a package is trying to ignore itself, causing a loop.
            Please resolve by removing the offending ignored_packages setting."

            When trying to uninstall several package at once, then here I am unignoring them all at once.

            Package Control: Advanced Install Package
            https://github.com/wbond/package_control/issues/1191

            @param flush_everything     set all remaining packages as unignored
        """

        if flush_everything:
            self.unignore_some_packages( g_next_packages_to_ignore )
            self.clearNextIgnoredPackages()

        else:
            log( 1, "Adding package to unignore list: %s" % str( package_name ) )
            self.uningoredPackagesToFlush += 1

            if self.uningoredPackagesToFlush >= len( g_next_packages_to_ignore ):
                self.unignore_some_packages( g_next_packages_to_ignore )
                self.clearNextIgnoredPackages()


    def clearNextIgnoredPackages(self):
        del g_next_packages_to_ignore[:]
        self.uningoredPackagesToFlush = 0


    def unignore_some_packages(self, packages_list):
        """
            Flush just a few items each time.
        """
        log( 1, "Unignoring %d packages..." % len( packages_list ) )

        if len( packages_list ):
            # This should remove them from the `in_process` list on the Package Control.sublime-settings file
            self.package_disabler.reenable_package( packages_list, "install" if self.isInstaller else "remove" )
            time.sleep( 1.7 )

            # Let the packages be unloaded by Sublime Text while ensuring anyone is putting them back in
            self.setup_packages_ignored_list( packages_to_remove=packages_list )


    def setup_packages_ignored_list(self, packages_to_add=[], packages_to_remove=[]):
        """
            Something, somewhere is setting the ignored_packages list to `["Vintage"]`. Then ensure we
            override this.
        """
        currently_ignored = g_userSettings.get( "ignored_packages", [] )
        log( 1, "Currently ignored packages: " + str( currently_ignored ) )

        packages_to_add.sort()
        packages_to_remove.sort()

        log( 1, "Ignoring the packages:      " + str( packages_to_add ) )
        log( 1, "Unignoring the packages:    " + str( packages_to_remove ) )

        currently_ignored = [package_name for package_name in currently_ignored if package_name not in packages_to_remove]
        unique_list_append( currently_ignored, packages_to_add )

        currently_ignored.sort()

        for interval in range( 0, 27 ):
            g_userSettings.set( "ignored_packages", currently_ignored )
            sublime.save_settings( self.channelSettings['USER_SETTINGS_FILE'] )

            time.sleep( 1.7 )

            new_ignored_list = g_userSettings.get( "ignored_packages", [] )
            log( 1, "Currently ignored packages: " + str( new_ignored_list ) )

            if new_ignored_list:

                if len( new_ignored_list ) == len( currently_ignored ) \
                        and new_ignored_list == currently_ignored:

                    break

        # Progressively saves the installation data, in case the user closes Sublime Text
        self.save_default_settings()


    def add_folders_and_files_for_removal(self, root_source_folder, relative_path):
        add_path_if_not_exists( g_folders_to_uninstall, relative_path )

        for source_folder, directories, files in os.walk( root_source_folder ):

            for folder in directories:
                source_file   = os.path.join( source_folder, folder )
                relative_path = convert_absolute_path_to_relative( source_file )

                add_path_if_not_exists( g_folders_to_uninstall, relative_path )

            for file in files:
                source_file   = os.path.join( source_folder, file )
                relative_path = convert_absolute_path_to_relative( source_file )

                add_path_if_not_exists( g_files_to_uninstall, relative_path )


    def add_package_to_installation_list(self, package_name):
        """
            When the installation is going on the PackagesManager will be installed. If the user restart
            Sublime Text after doing it, on the next time Sublime Text starts, the Package Control and
            the PackagesManager will kill each other and probably end up uninstalling all the packages
            installed.

            So, here we try to keep things nice by syncing both `Package Control` and `PackagesManager`
            settings files.
        """

        if g_package_control_settings and not self.isDevelopment:
            installed_packages = get_dictionary_key( g_package_control_settings, 'installed_packages', [] )
            add_item_if_not_exists( installed_packages, package_name )

            packagesmanager = os.path.join( self.channelSettings['USER_FOLDER_PATH'], g_packagesmanager_name )
            write_data_file( packagesmanager, sort_dictionary( g_package_control_settings ) )

        add_item_if_not_exists( g_packages_to_uninstall, package_name )

        # Progressively saves the installation data, in case the user closes Sublime Text
        self.save_default_settings()


    def copy_overrides(self, root_source_folder, root_destine_folder, move_files=False, is_to_replace=True):
        """
            Python How To Copy Or Move Folders Recursively
            http://techs.studyhorror.com/python-copy-move-sub-folders-recursively-i-92

            Python script recursively rename all files in folder and subfolders
            https://stackoverflow.com/questions/41861238/python-script-recursively-rename-all-files-in-folder-and-subfolders

            Force Overwrite in Os.Rename
            https://stackoverflow.com/questions/8107352/force-overwrite-in-os-rename
        """
        installed_files   = []
        installed_folders = []

        # Call this if operation only one time, instead of calling the for every file.
        if move_files:

            def operate_file(source_file, destine_folder):
                shutil.move( source_file, destine_folder )

        else:

            def operate_file(source_file, destine_folder):
                shutil.copy( source_file, destine_folder )

        for source_folder, directories, files in os.walk( root_source_folder ):
            destine_folder = source_folder.replace( root_source_folder, root_destine_folder)

            if not os.path.exists( destine_folder ):
                os.mkdir( destine_folder )

            for file in files:
                source_file  = os.path.join( source_folder, file )
                destine_file = os.path.join( destine_folder, file )

                # print( ( "Moving" if move_files else "Coping" ), "file:", source_file, "to", destine_file )
                if os.path.exists( destine_file ):

                    if is_to_replace:
                        delete_read_only_file( destine_file )

                    else:
                        continue

                # Python: Get relative path from comparing two absolute paths
                # https://stackoverflow.com/questions/7287996/python-get-relative-path-from-comparing-two-absolute-paths
                relative_file_path   = self.convert_absolute_path_to_relative( destine_file )
                relative_folder_path = self.convert_absolute_path_to_relative( destine_folder )

                operate_file(source_file, destine_folder)

                add_path_if_not_exists( installed_files, relative_file_path )
                add_path_if_not_exists( installed_folders, relative_folder_path )

        log( 1, "copy_overrides, installed_files:   " + str( installed_files ) )
        log( 1, "copy_overrides, installed_folders: " + str( installed_folders ) )
        return installed_files, installed_folders


    def convert_absolute_path_to_relative(self, file_path):
        relative_path = os.path.commonprefix( [ self.channelSettings['CHANNEL_ROOT_DIRECTORY'], file_path ] )
        relative_path = os.path.normpath( file_path.replace( relative_path, "" ) )

        return convert_to_unix_path(relative_path)


    def ask_user_for_which_packages_to_install(self, packages_names, packages_infos=[]):
        can_continue  = [False, False]
        active_window = sublime.active_window()

        packages_informations            = self.packagesInformations()
        selected_packages_to_not_install = []

        for package_name in packages_names:

            if package_name in self.channelSettings['FORBIDDEN_PACKAGES']:
                packages_informations.append( [ package_name, self.notInstallMessage ] )

            else:
                packages_informations.append( [ package_name, self.install_message ] )

        def on_done(item_index):

            if item_index < 1:
                can_continue[0] = True
                can_continue[1] = True
                return

            if item_index == 1:
                log.insert_empty_line()
                log( 1, "Continuing the %s after the packages pick up..." % self.installationType )

                can_continue[0] = True
                return

            package_information = packages_informations[item_index]
            package_name        = package_information[0]

            if package_name not in self.channelSettings['FORBIDDEN_PACKAGES']:

                if package_information[1] == self.install_message:
                    log( 1, "%s the package: %s" % ( "Removing" if self.isInstaller else "Keeping", package_name ) )

                    package_information[1] = self.uninstall_message
                    selected_packages_to_not_install.append( package_name )

                else:
                    log( 1, "%s the package: %s" % ( "Adding" if self.isInstaller else "Removing", package_name ) )

                    package_information[1] = self.install_message
                    selected_packages_to_not_install.remove( package_name )

            else:
                log( 1, "The package %s must be %s. " % ( package_name, self.word_installed ) +
                        "If you do not want to %s this package, cancel the %s process." % ( self.word_install, self.installationType ) )

            show_quick_panel( item_index )

        def show_quick_panel(selected_index=0):
            active_window.show_quick_panel( packages_informations, on_done, sublime.KEEP_OPEN_ON_FOCUS_LOST, selected_index )

        show_quick_panel()

        # show_quick_panel is a non-blocking function, but we can only continue after on_done being called
        while not can_continue[0]:
            time.sleep(1)

        # Show up the console, so the user can follow the process.
        sublime.active_window().run_command( "show_panel", {"panel": "console", "toggle": False} )

        if can_continue[1]:
            log.insert_empty_line()
            raise InstallationCancelled( "The user closed the %s's packages pick up list." % self.word_installer )

        for package_name in selected_packages_to_not_install:
            g_packages_not_installed.append( package_name )

            target_index = packages_names.index( package_name )
            del packages_names[target_index]

            if len( packages_infos ):
                del packages_infos[target_index]

        # Progressively saves the installation data, in case the user closes Sublime Text
        self.save_default_settings()


    def check_installed_packages_alert(self, maximum_attempts=10):
        """
            Show a message to the user observing the Sublime Text console, so he know the process is not
            finished yet.
        """
        log( 1, "Looking for new tasks... %s seconds remaining." % str( maximum_attempts ) )
        maximum_attempts -= 1

        if maximum_attempts > 0:

            if g_is_running:
                sublime.set_timeout_async( lambda: self.check_installed_packages_alert( maximum_attempts ), 1000 )

            else:
                log( 1, "Finished looking for new tasks... The installation is complete." )


    def check_installed_packages(self, maximum_attempts=10):
        """
            Wait PackagesManager to load the found dependencies, before announcing it to the user.

            Display warning when the uninstallation process is finished or ask the user to restart
            Sublime Text to finish the uninstallation.

            Compare the current uninstalled packages list with required packages to uninstall, and if
            they differ, attempt to uninstall they again for some times. If not successful, stop trying
            and warn the user.
        """
        log( _grade(), "Finishing %s... maximum_attempts: " % self.installationType + str( maximum_attempts ) )
        maximum_attempts -= 1

        if not g_is_running:
            self.accumulative_unignore_user_packages( flush_everything=True )

            if not self.isUpdateInstallation:
                sublime.message_dialog( end_user_message( """\
                        The {channel_name} {type} was successfully completed.

                        You need to restart Sublime Text to {prefix}load the {installed} packages and finish
                        {prefix}installing the {prefix}used dependencies.

                        Check you Sublime Text Console for more information.
                        """.format( channel_name=self.channelSettings['CHANNEL_PACKAGE_NAME'], type=self.installationType,
                                prefix=self.word_prefix, installed=self.word_installed )
                    )
                )

                sublime.active_window().run_command( "show_panel", {"panel": "console", "toggle": False} )

            print_failed_repositories( self.failedRepositories )
            return

        if maximum_attempts > 0:
            sublime.set_timeout_async( lambda: self.check_installed_packages( maximum_attempts ), 2000 )

        else:
            sublime.error_message( end_user_message( """\
                    The {channel_name} {type} could NOT be successfully completed.

                    Check you Sublime Text Console for more information.

                    If you want help fixing the problem, please, save your Sublime Text Console output,
                    so later others can see what happened try to fix it.
                    """.format( channel_name=self.channelSettings['CHANNEL_PACKAGE_NAME'], type=self.installationType )
                )
            )

            self.accumulative_unignore_user_packages( flush_everything=True )

            print_failed_repositories( self.failedRepositories )
            sublime.active_window().run_command( "show_panel", {"panel": "console", "toggle": False} )


def end_user_message(message):
    # This is here because it is almost the last thing to be done
    global g_is_running
    g_is_running = False

    log.insert_empty_line()
    log.clean( 1, message )

    return wrap_text( message )


def is_allowed_to_run():
    global g_is_running

    if g_is_running:
        print( "You are already running a command. Wait until it finishes or restart Sublime Text" )
        return False

    g_is_running = ALL_RUNNING_CONTROL_FLAGS
    return True


def satisfy_dependencies(SatisfyDependenciesThread, package_manager):
    thread = SatisfyDependenciesThread( package_manager )

    thread.start()
    thread.join()


def load_installation_settings_file(self):
    channel_settings = self.channelSettings

    global PACKAGE_CONTROL
    global PACKAGESMANAGER

    global g_package_control_name
    global g_packagesmanager_name

    g_package_control_name = "Package Control.sublime-settings"
    g_packagesmanager_name = "PackagesManager.sublime-settings"

    PACKAGESMANAGER = os.path.join( channel_settings['USER_FOLDER_PATH'], g_packagesmanager_name )
    PACKAGE_CONTROL = os.path.join( channel_settings['USER_FOLDER_PATH'], g_package_control_name )

    global g_userSettings
    global g_channelDetails
    global g_default_ignored_packages

    g_userSettings   = sublime.load_settings( channel_settings['USER_SETTINGS_FILE'] )
    g_channelDetails = load_data_file( channel_settings['CHANNEL_INSTALLATION_DETAILS'] )

    # Contains the original user's ignored packages.
    log( _grade(), "Loaded g_channelDetails: " + str( g_channelDetails ) )
    g_default_ignored_packages = g_userSettings.get( 'ignored_packages', [] )

    global g_packages_to_uninstall
    global g_files_to_uninstall
    global g_folders_to_uninstall
    global g_packages_to_unignore
    global g_next_packages_to_ignore
    global g_packages_not_installed
    global g_installation_type

    g_packages_to_uninstall   = get_dictionary_key( g_channelDetails, 'packages_to_uninstall', [] )
    g_packages_to_unignore    = get_dictionary_key( g_channelDetails, 'packages_to_unignore', [] )
    g_files_to_uninstall      = get_dictionary_key( g_channelDetails, 'files_to_uninstall', [] )
    g_folders_to_uninstall    = get_dictionary_key( g_channelDetails, 'folders_to_uninstall', [] )
    g_next_packages_to_ignore = get_dictionary_key( g_channelDetails, 'next_packages_to_ignore', [] )
    g_packages_not_installed  = get_dictionary_key( g_channelDetails, 'packages_not_installed', [] )
    g_installation_type       = get_dictionary_key( g_channelDetails, 'installation_type', channel_settings['INSTALLATION_TYPE'] )

    # When the installation was interrupted, there will be ignored packages which are pending to
    # uningored. Then these packages must to be loaded when the installer starts again.
    log( _grade(), "load_installation_settings_file, unignoring initial packages... " + str( g_next_packages_to_ignore ) )
    self.unignore_some_packages( g_next_packages_to_ignore )

    log( _grade(), "load_installation_settings_file, g_default_ignored_packages:        " + str( g_default_ignored_packages ) )
    log( _grade(), "load_installation_settings_file, PACKAGES_TO_IGNORE_ON_DEVELOPMENT: "
            + str( channel_settings['PACKAGES_TO_IGNORE_ON_DEVELOPMENT'] ) )

