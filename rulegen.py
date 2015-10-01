#!/usr/bin/env python3

"""Generate a random string according to given generation rules."""
# Copyright © 2015 Timothy Pederick.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

# Standard library imports.
from collections import namedtuple
from contextlib import contextmanager
import csv
import os
import os.path
import random
import sqlite3

# Local imports.
from ruleparser import all_terminals

# Enable boolean handling in SQLite.
sqlite3.register_adapter(bool, int)
sqlite3.register_converter('BOOLEAN', lambda dat: bool(int(dat)))

class Rulegen:
    """A rules-based random generator."""
    def __init__(self, data_prefix, data_dir=None, csvfile=None, dbfile=None):
        """Initialise the generator."""
        self.data_prefix = data_prefix
        self.data_dir = os.getcwd() if data_dir is None else data_dir
        self.csvfile = (os.path.join(self.data_dir, self.data_prefix + '.csv')
                        if csvfile is None else csvfile)
        self.dbfile = (os.path.join(self.data_dir, self.data_prefix + '.db')
                       if dbfile is None else dbfile)
