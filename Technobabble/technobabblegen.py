#!/usr/bin/env python3

"""Random sci-fi technobabble generator."""

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
DATA_PREFIX = 'technobabble'
DATA_DIR = os.getcwd()
DEFAULT_CSVFILE = os.path.join(DATA_DIR, DATA_PREFIX + '.csv')
DEFAULT_DBFILE = os.path.join(DATA_DIR, DATA_PREFIX + '.db')

# CSV data format.
csv_format = namedtuple('csv_format', ('Prefix', 'Adjective',
                                       'Adverb', 'PatientOrObject',
                                       'IsPatientOnly', 'IsObjectUncountable',
                                       'PresentParticiple', 'PastParticiple',
                                       'Agent', 'IsAgentUncountable'))

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
            cur.execute('DROP TABLE IF EXISTS Elements')
            cur.execute('CREATE TABLE Elements'
                        ' (ElementID INTEGER PRIMARY KEY AUTOINCREMENT'
                        ', Prefix TEXT'
                        ', Adjective TEXT'
                        ', Adverb TEXT'
                        ', PatientOrObject TEXT'
                        ', IsPatientOnly BOOLEAN NOT NULL'
                        ', IsObjectUncountable BOOLEAN NOT NULL'
                        ', PresentParticiple TEXT'
                        ', PastParticiple TEXT'
                        ', Agent TEXT'
                        ', IsAgentUncountable BOOLEAN NOT NULL'
                        ' )')

            # Read data file and populate table.
            cur.executemany('INSERT INTO Elements'
                            ' (Prefix, Adjective, Adverb,'
                            '  PatientOrObject, IsPatientOnly,'
                            '  IsObjectUncountable, PresentParticiple,'
                            '  PastParticiple, Agent, IsAgentUncountable)'
                            ' VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                            csvdata())
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
        # Handle the case of the Object pseudo-column.
        where_addenda = ''
        if colname == 'Object':
            colname = 'PatientOrObject'
            where_addenda = ' AND IsPatientOnly = 0'
        # Build a where clause to avoid repeats.
        values = []
        check_col = None
        if repeat_avoider is not None:
            check_col = repeat_avoider.idcol
            avoid_this = ' AND {} != ?'.format(check_col)
            avoids = []
            for seen_id in repeat_avoider.seen_ids:
                avoids.append(avoid_this)
                values.append(seen_id)
            if len(avoids) > 0:
                where_addenda += ''.join(avoids)
        query = ('SELECT {0}{1}'
                 ' FROM Elements'
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
    """Generate one random technobabble item."""
    with avoid_repeats('ElementID') as ar:
        return ' '.join((description(ar), thing(ar)))

def description(repeat_avoider=None):
    if maybe():
        return adjective_phrase(repeat_avoider)
    else:
        parts = [descriptor(repeat_avoider)]
        if maybe():
            parts.insert(0, adjective_phrase(repeat_avoider))
        return ' '.join(parts)

def descriptor(repeat_avoider=None):
    if maybe():
        return adjective(repeat_avoider)
    else:
        parts = [patient(repeat_avoider)]
        if maybe():
            parts.insert(0, getdata('Prefix', repeat_avoider))
        return '-'.join(parts)

def adjective_phrase(repeat_avoider=None):
    if maybe():
        return adverb_phrase(repeat_avoider)
    else:
        parts = [adjective(repeat_avoider)]
        if maybe():
            parts.insert(0, pre_adjective(repeat_avoider))
        return ' '.join(parts)

def pre_adjective(repeat_avoider=None):
    parts = [adjective(repeat_avoider)]
    if maybe():
        parts.insert(0, getdata('Prefix', repeat_avoider))
    return '-'.join(parts)

def adjective(repeat_avoider=None):
    if maybe():
        return getdata('Adjective', repeat_avoider)
    elif maybe():
        return getdata('PastParticiple', repeat_avoider)
    else:
        return getdata('PresentParticiple', repeat_avoider)

def adverb_phrase(repeat_avoider=None):
    return '-'.join((getdata('Adverb', repeat_avoider),
                     getdata('PastParticiple' if maybe else 'Adjective',
                             repeat_avoider)))

def thing(repeat_avoider=None):
    parts = [an_object(repeat_avoider)]
    if maybe():
        parts.insert(0, patient(repeat_avoider))
    return ' '.join(parts)

def patient(repeat_avoider=None):
    return getdata('PatientOrObject' if maybe() else 'Agent', repeat_avoider)

def an_object(repeat_avoider=None):
    return getdata('Agent' if maybe() else 'Object', repeat_avoider)

if __name__ == '__main__':
    print(generate())
