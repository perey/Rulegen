#!/usr/bin/env python3

"""Random academic field generator."""

# Standard library imports.
from collections import namedtuple
from contextlib import contextmanager
import csv
import os
import os.path
import random
import sqlite3

# Enable boolean handling in SQLite.
sqlite3.register_adapter(bool, int)
sqlite3.register_converter('BOOLEAN', lambda dat: bool(int(dat)))

# Locate the data files.
DATA_PREFIX = 'academia'
DATA_DIR = os.getcwd()
DEFAULT_CSVFILE = os.path.join(DATA_DIR, DATA_PREFIX + '.csv')
DEFAULT_DBFILE = os.path.join(DATA_DIR, DATA_PREFIX + '.db')

# CSV data format.
csv_format = namedtuple('csv_format', ('MetaPrefix', 'StandalonePrefix',
                                       'StrictPrefix', 'IsolatablePrefix',
                                       'StrictSuffix', 'IsODropping',
                                       'StandaloneSuffix', 'PrefixingSuffix'))

# Choose one of two options at random.
maybe = lambda: random.random() < 0.5

def csvdata(csvfilename=DEFAULT_CSVFILE):
    """Read in data from the given CSV file."""
    return map(csv_format._make, csv.reader(open(csvfilename, encoding='utf-8',
                                                 newline='')))

def build_db(dbfilename=DEFAULT_DBFILE):
    """(Re)build the SQLite database that holds the data."""
    # Connect to the database file.
    conn = sqlite3.connect(dbfilename, detect_types=sqlite3.PARSE_DECLTYPES)
    try:
        with conn:
            cur = conn.cursor()
            # Create or replace table.
            cur.execute('DROP TABLE IF EXISTS Roots')
            cur.execute('CREATE TABLE Roots'
                        ' (RootID INTEGER PRIMARY KEY AUTOINCREMENT'
                        ', MetaPrefix TEXT'
                        ', StandalonePrefix TEXT'
                        ', StrictPrefix TEXT'
                        ', IsolatablePrefix TEXT'
                        ', StrictSuffix TEXT'
                        ', IsODropping BOOLEAN NOT NULL'
                        ', StandaloneSuffix TEXT'
                        ', PrefixingSuffix TEXT'
                        ' )')

            # Read data file and populate table.
            cur.executemany('INSERT INTO Roots'
                            ' (MetaPrefix, StandalonePrefix,'
                            '  StrictPrefix, IsolatablePrefix,'
                            '  StrictSuffix, IsODropping,'
                            '  StandaloneSuffix, PrefixingSuffix)'
                            ' VALUES (?, ?, ?, ?, ?, ?, ?, ?)', csvdata())
    finally:
        conn.close()

class RepeatAvoider:
    def __init__(self, idcol):
        self.idcol = idcol
        self.seen_ids = set()

@contextmanager
def avoid_repeats(idcol):
    """Keep track of seen values from the database."""
    yield RepeatAvoider(idcol)

def getdata(colname, repeat_avoider=None, dbfilename=DEFAULT_DBFILE):
    """Get one random value from the database."""
    if not os.path.isfile(dbfilename):
        build_db(dbfilename=dbfilename)

    conn = sqlite3.connect(dbfilename, detect_types=sqlite3.PARSE_DECLTYPES)
    try:
        cur = conn.cursor()
        # Build a where clause to avoid repeats.
        values = []
        check_col = None
        where_addenda = ''
        if repeat_avoider is not None:
            check_col = repeat_avoider.idcol
            avoid_this = ' AND {} != ?'.format(check_col)
            avoids = []
            for seen_id in repeat_avoider.seen_ids:
                avoids.append(avoid_this)
                values.append(seen_id)
            if len(avoids) > 0:
                where_addenda = ''.join(avoids)
        query = ('SELECT {0}{1}'
                 ' FROM Roots'
                 ' WHERE {0} IS NOT NULL'
                 '  AND {0} != ""{2}'
                 ' ORDER BY random()'
                 ' LIMIT 1'.format(colname, ('' if check_col is None else
                                             ', ' + check_col),
                                   where_addenda))
        cur.execute(query, values)
        row = cur.fetchone()
        if repeat_avoider is not None:
            repeat_avoider.seen_ids.add(row[1])
        return row[0]
    finally:
        conn.close()

def generate():
    """Generate one random academic field."""
    with avoid_repeats('RootID') as ar:
        if maybe():
            return multipart_mainword(ar)
        else:
            parts = list(preword(ar) for _ in range(random.randrange(1, 3)))
            parts.append(mainword(ar))
            return ' '.join(parts)

def preword(repeat_avoider=None):
    if maybe():
        return standalone_preword(repeat_avoider)
    else:
        parts = [main_prefix(repeat_avoider)]
        if maybe():
            parts.append(getdata('IsolatablePrefix', repeat_avoider))
        parts.append(getdata('PrefixingSuffix', repeat_avoider))
        return ''.join(parts)

def standalone_preword(repeat_avoider=None):
    parts = [getdata('StandalonePrefix', repeat_avoider)]
    if maybe():
        parts.insert(0, getdata('MetaPrefix', repeat_avoider))
    return ''.join(parts)

def mainword(repeat_avoider=None):
    return (simple_mainword(repeat_avoider) if maybe() else
            multipart_mainword(repeat_avoider))

def multipart_mainword(repeat_avoider=None):
    return ''.join((main_prefix(repeat_avoider),
                    simple_mainword(repeat_avoider)))

def main_prefix(repeat_avoider=None):
    if maybe():
        return getdata('StrictPrefix', repeat_avoider)
    else:
        parts = [getdata('IsolatablePrefix', repeat_avoider)]
        if maybe():
            parts.insert(0, getdata('StrictPrefix', repeat_avoider))
        return ''.join(parts)

def simple_mainword(repeat_avoider=None):
    return (getdata('StandaloneSuffix', repeat_avoider) if maybe() else
            ''.join((getdata('IsolatablePrefix', repeat_avoider),
                     getdata('StrictSuffix', repeat_avoider))))

if __name__ == '__main__':
    print(generate())
