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
from ruleparser import (all_terminals, parse_rules, parse_terminals, Literal,
                        DBLookup)

# Enable boolean handling in SQLite.
sqlite3.register_adapter(bool, int)
sqlite3.register_converter('BOOLEAN', lambda dat: bool(int(dat)))

class Rulegen:
    """A rules-based random generator.

    A random generator is initialised from two text files: a CSV file
    containing words or word elements ("roots"), and a rules file
    containing generation rules in the format defined by the ruleparser
    module.

    To generate strings, the generator connects to a SQLite database
    file on disk (creating it from the above files first if it does not
    exist). This database has two tables, called by default "Roots" and
    "Results", corresponding to the CSV and rules files respectively.

    (As a result of this setup, it is possible for a generator to
    operate with only the database file.)

    Class attributes:
        The following attributes set some defaults for the names and
        schemas of the database files. Override them in a subclass, or
        by assigning instance attributes with the same names, to change
        the default.
        roots_table -- The name of the "Roots" table.
        roots_idcol -- The column of the "Roots" table that holds a
            unique row identifier.
        results_table -- The name of the "Results" table.
        results_idcol -- The column of the "Results" table that holds a
            unique row identifier.
        results_idcol -- The column of the "Roots" table that holds the
            data.
        idcol_type -- The SQLite type declaration applicable to the
            above-mentioned *_idcol attributes.

    Instance attributes:
        data_prefix -- A default filename (minus the extension) to use
            for all data files.
        data_dir -- A directory name (absolute or relative) where the
            data files are found by default.
        csvfile, rulefile, dbfile -- The paths and filenames of the CSV,
            rules, and database files.
        rules -- The parse tree for the rules file, as produced by the
            ruleparser module. Read-only.

    """
    roots_table, roots_idcol = 'Roots', 'RootID'
    results_table, results_idcol, results_datacol = ('Results', 'ResultID',
                                                     'Result')
    idcol_type = 'INTEGER PRIMARY KEY AUTOINCREMENT'

    def __init__(self, data_prefix, data_dir=None, csvfile=None, rulefile=None,
                 dbfile=None):
        """Initialise the generator.

        Keyword arguments:
            data_prefix -- As the instance attribute.
            data_dir -- As the instance attribute. The default is the
                current working directory.
            csvfile, rulefile, dbfile -- As the instance attributes. The
                defaults are built from the above two parameters, with
                extensions ".csv", ".rules", and ".db", respectively.

        """
        self.data_prefix = data_prefix
        self.data_dir = os.getcwd() if data_dir is None else data_dir
        (self.csvfile, self.rulefile,
         self.dbfile) = ((os.path.join(self.data_dir, self.data_prefix + ext)
                          if file is None else file)
                         for file, ext in ((csvfile, '.csv'),
                                           (rulefile, '.rules'),
                                           (dbfile, '.db')))

        self._rules = self._headings = self._seen_ids = None

    @property
    def rules(self):
        if self._rules is None:
            self._rules = parse_rules(self.rulefile)
        return self._rules

    def guess_type(self, heading):
        """Guess the SQLite type of a column based on its heading.

        The guessed type is set by the generator's idcol_type attribute
        if the heading is the same as either of the *_idcol attributes.
        If not, but the column heading starts with "Is" followed by a
        capital letter, the guessed type is suitable for Boolean data.
        Otherwise, the guessed type is "TEXT".

        Keyword arguments:
            heading -- A string containing a column heading.

        Returns:
            A string containing a SQLite data type declaration.

        """
        bool_prefix = 'Is'

        return (self.idcol_type if heading in (self.roots_idcol,
                                               self.results_idcol) else
                'BOOLEAN NOT NULL'
                if (heading.startswith(bool_prefix) and
                    heading[len(bool_prefix)].isupper()) else
                'TEXT')

    def headings(self, with_id=False, with_types=False, sep=', '):
        """Get the data column headings as a string.

        Specifically, these are the columns of the generator's "Roots"
        table. The "Results" table only has one data column, and its
        heading is stored in the generator's results_datacol attribute.

        Keyword arguments:
            with_id -- True if the ID column of the table should be
                included. The default is False.
            with_types -- True if the output should include the data
                type declaration for each column (suitable for e.g. a
                SQL CREATE TABLE statement). The default is False.
            sep -- The separator to use in the output string. The
                default is a comma and space (", ").

        Returns:
            A string containing the column headings, separated by the
            sep argument.

        """
        if self._headings is None:
            # Call the CSV reader so that self._headings is set.
            self.read_csv()

        assert self._headings is not None
        headings = [self.roots_idcol] if with_id else []
        headings.extend(self._headings)

        return sep.join(repr(heading) +
                        (' ' + self.guess_type(heading) if with_types else '')
                        for heading in headings)

    def read_csv(self):
        """Read data from the CSV data file.

        Returns:
            A list of named-tuple instances.

        """
        with open(self.csvfile, encoding='utf-8') as file:
            reader = csv.reader(file)
            # Fetch the column headings from the first line. Don't include it
            # in the output!
            self._headings = next(reader)

            # Stick each remaining line in a named tuple.
            csv_format = namedtuple('csv_format', self._headings)

            # Lazy evaluation of a generator causes problems when other
            # methods need to use self._headings, so don't be a generator.
            # Just return the results instead of yielding each one.
            return list(csv_format(*row) for row in reader)

    def build_db(self):
        """(Re)build the SQLite database."""
        # Connect to the database file.
        conn = sqlite3.connect(self.dbfile,
                               detect_types=sqlite3.PARSE_DECLTYPES)
        try:
            # We need the CSV reader later, so let's call it now so that
            # self._headings is set.
            csv_rows = self.read_csv()

            cur = conn.cursor()
            # Create or replace the tables.
            cur.execute('DROP TABLE IF EXISTS {!r}'.format(self.roots_table))
            cur.execute('DROP TABLE IF EXISTS {!r}'.format(self.results_table))
            cur.execute('CREATE TABLE {!r} '
                        '({})'.format(self.roots_table,
                                      self.headings(with_id=True,
                                                    with_types=True)))
            cur.execute('CREATE TABLE {!r}'
                        ' ({!r} {}'
                        ', {!r} TEXT)'.format(self.results_table,
                                              self.results_idcol,
                                              self.idcol_type,
                                              self.results_datacol))

            # Read in the CSV data and insert it into the table.
            cur.executemany('INSERT INTO {!r} ({})'
                            ' VALUES ({})'.format(self.roots_table,
                                                  self.headings(),
                                                  ', '.join('?' for _ in
                                                            self._headings)),
                            csv_rows)
            # Parse the rules and insert each result format into the table.
            cur.executemany('INSERT INTO {!r} ({})'
                            ' VALUES (?)'.format(self.results_table,
                                                 self.results_datacol),
                            # Stick each terminal sequence in a one-item tuple
                            # to stop the string being interpreted as a
                            # sequence of data values.
                            ((result,) for result in
                             all_terminals(self.rules)))

            conn.commit()
        finally:
            conn.close()

    def get_data(self, colname, table=None, idcol=None):
        """Get one random value from the database.

        Internally, the generator's _seen_ids attribute is used to
        ensure that successive calls to get_data() do not repeat rows.
        This private attribute is set (and reset) by the generate()
        method.

        Keyword arguments:
            colname -- The database column name from which data is to be
                retrieved.
            table -- The name of the table (in this generator's database
                file) from which data is to be retrieved. The default is
                the generator's roots_table attribute.
            idcol -- The database column name that stores a unique
                identifier for each row. The default is the generator's
                roots_idcol attribute (or results_idcol, if the table
                argument is supplied and is equal to the results_table
                attribute).

        Returns:
            A string.

        """
        if not os.path.isfile(self.dbfile):
            self.build_db()

        if table is None:
            table = self.roots_table
        if idcol is None:
            idcol = (self.results_idcol if table == self.results_table else
                     self.roots_idcol)

        conn = sqlite3.connect(self.dbfile,
                               detect_types=sqlite3.PARSE_DECLTYPES)
        try:
            cur = conn.cursor()
            # Build a WHERE clause that avoids repeats.
            values = []
            select_addendum = where_addenda = ''
            if self._seen_ids is not None:
                select_addendum = ', t.{!r}'.format(idcol)
                avoid_this = ' AND t.{!r} != ?'.format(idcol)
                avoids = []
                for seen_id in self._seen_ids:
                    avoids.append(avoid_this)
                    values.append(seen_id)
                if len(avoids) > 0:
                    where_addenda = ''.join(avoids)
            query = ('SELECT t.{1!r}{2}'
                     ' FROM {0!r} t'
                     ' WHERE t.{1!r} IS NOT NULL'
                     '  AND t.{1!r} != ""{3}'
                     ' ORDER BY random()'
                     ' LIMIT 1'.format(table, colname,
                                       select_addendum, where_addenda))
            cur.execute(query, values)
            row = cur.fetchone()
            if self._seen_ids is not None:
                self._seen_ids.add(row[1])

            # We're finished with the connection... but don't commit, because
            # nothing (should have) changed!
            return row[0]
        finally:
            conn.close()

    def generate(self):
        """Generate a random string according to the generator rules.

        Returns:
            A string.

        """
        # Select a random output format. Don't save seen data rows, yet.
        self._seen_ids = None
        fmt = self.get_data(self.results_datacol, self.results_table,
                            self.results_idcol)

        # This is a list of 2-tuples. The first element of each is the text to
        # add to the string; the second is None when the text came from a
        # string literal, or the name of the column when it came from a
        # database lookup.
        result = []

        # Start saving seen data rows.
        self._seen_ids = set()

        # Split the format into a sequence of database lookups and string
        # literals.
        for token in parse_terminals(fmt):
            # Push string literals straight to output, but grab a random element
            # from the database for each database lookup.
            if isinstance(token, Literal):
                result.append((token.content, None))
            else:
                assert isinstance(token, DBLookup)
                result.append((self.get_data(token.content), token.content))

        # Apply any post-processing.
        self.postprocess(result)

        return ''.join(text for text, _ in result)

    def postprocess(self, result):
        """Apply generator-specific processing to generated output.

        Keyword arguments:
            result -- A list (or other mutable sequence) of 2-tuples.
                Each tuple contains a string and a column name (or None
                if the string came from a literal).

        Returns:
            None (the result argument is modified in-place).

        """
        return
