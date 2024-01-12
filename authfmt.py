#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
'''
Script using the bibtexparser module to cleanup_record and pretty print our
bibliography.
'''
import argcomplete, argparse
import sys
from io import StringIO
from argparse import ArgumentParser
from difflib import ndiff
from collections import OrderedDict
import re
import string
import itertools
from pprint import pprint

import bibtexparser as bp
from bibtexparser.bibdatabase import BibDataStringExpression, BibDataString
from bibtexparser.bparser import BibTexParser
from bibtexparser.bwriter import BibTexWriter
from bibtexparser.latexenc import unicode_to_latex_map
from splitnames import splitname

import data

from bibfmt import _fixdb

NON_ALPHANUMERIC_RE = re.compile(r"[^0-9a-zA-Z]+")
NON_ALPHANUMERIC_WITH_SPACES_AND_DASHES_RE = re.compile(r"[^ 0-9a-zA-Z-]+")
NUMERIC_RE = re.compile(r"[0-9]+")
ID_RE = re.compile(r"([a-zA-Z]+)([0-9]+)([a-zA-Z]+)?")

FIELDS_TO_REMOVE = [
    # "bibsource",
    # "biburl",
    # # "doi",
    # "timestamp",
    # # "url",
]


def check_min_version():
    '''
    Ensure that a new enough version of bibtexparser is used.
    '''
    vers = bp.__version__.split('.')
    if (int(vers[0]), int(vers[1])) < (1, 2):
        raise RuntimeError('The script requires at least bibtexparser version 1.2.')

def is_ascii(x):
    '''
    Reurn true if the given string contains ascii symbols only.
    '''
    try:
        x.encode('ascii')
        return True
    except UnicodeEncodeError:
        return False

# Map from unicode symbols to latex expressions.
#
# The bibtexparser.latexenc module also maps some ascii characters to unicode
# symbols. Such characters are ignored in the map.
UNICODE_TO_LATEX = {key: value
                    for key, value in unicode_to_latex_map.items()
                    if not is_ascii(key)}

def apply_on_expression(x, f):
    '''
    Apply the function f for converting strings to bibtex expressions as
    returned by the bibtexparser module.
    '''
    if isinstance(x, str):
        return f(x)
    if isinstance(x, BibDataStringExpression):
        x.apply_on_strings(f)
    return x

def cleanup_expression(x):
    '''
    Convert the given string containing unicode symbols into a string with
    latex escapes only.
    '''
    ret = []
    for char in x:
        if char in (' ', '{', '}'):
            ret.append(char)
        else:
            ret.append(UNICODE_TO_LATEX.get(char, char))
    return ''.join(ret)

def cleanup_record(x):
    '''
    Cleanup a record as returned by the bibtexparser module.
    '''
    for val in x:
        if val in ('ID',):
            continue
        x[val] = apply_on_expression(x[val], cleanup_expression)
        if val.lower() == 'pages':
            x[val] = x[val].replace('--', '-')
    return x

def _parser(customization=cleanup_record):
    '''
    Return a configured bibtex parser.
    '''
    parser = BibTexParser()
    parser.interpolate_strings = False
    parser.customization = customization
    return parser

def _writer(sorted_entries=True):
    '''
    Return a configured bibtex writer.
    '''
    writer = BibTexWriter()
    writer.indent = '  '
    writer.order_entries_by = ('ID',) if sorted_entries else None
    writer.display_order = ['title', 'author', 'editor']
    return writer


#####################################################################################








def split_names_to_strs(names: str) -> list[str]:
    '''
    Split the given string containing people names into a list of strings representing the name of each person.
    '''
    return names.replace("\n", " ").split(' and ')

def split_names_to_dicts(names: str) -> list[dict]:
    '''
    Split the given string containing people names into a list of dictionaries representing the name of each person.
    '''
    return [splitname(name) for name in split_names_to_strs(names)]

def format_first_name(name: str) -> str:
    if len(name) > 2 and not name.startswith("{\\"):
        name = f"{name[0]}."
    return name

def format_name_dict(name: dict) -> dict:
    '''
    Format name reprented as a dictionary.
    '''
    if "first" in name:
        new_name = name.copy()
        first_name = " ".join(new_name["first"])
        new_name["first"] = [format_first_name(first_name)]
        return new_name
    return name

def dict_name_to_str(name: dict) -> str:
    '''
    Concatenate the name information into a string.
    '''
    first = " ".join(name.get("first", []))
    von = " ".join(name.get("von", []))
    last = " ".join(name.get("last", []))
    jr = " ".join(name.get("jr", []))
    previous = first != ""
    if previous and von:
        von = f" {von}"
    if previous and last:
        last = f" {last}"
    if previous and jr:
        jr = f" {jr}"
    return f"{first}{von}{last}{jr}"


def format_names(names: str) -> str:
    '''
    Format the given string containing people names.
    '''
    return ' and '.join(dict_name_to_str(format_name_dict(name)) for name in split_names_to_dicts(names))

def format_entry_names(entry):
    '''
    Format the names in the given entry.
    '''
    new_entry = entry.copy()
    if 'author' in new_entry:
        new_entry['author'] = format_names(new_entry['author'])
    if 'editor' in entry:
        new_entry['editor'] = format_names(entry['editor'])
    if new_entry == entry:
        return entry
    return new_entry

def format_entry(entry):
    '''
    Format the given entry.
    '''
    new_entry = format_entry_names(cleanup_record(entry))
    if new_entry == entry:
        return entry
    return new_entry

def format_bib(path):
    '''
    Format the given bibliography file.
    '''
    # read bibliography
    with open(path, "r") as f:
        db = _fixdb(bp.load(f, _parser(customization=format_entry)))

    # write the bibliography
    with open(path, "w") as f:
        bp.dump(db, f, _writer(sorted_entries=False))
   


def run():
    '''
    Run the applications.
    '''
    check_min_version()

    parser = ArgumentParser(
        prog='bibfmt',
        description='Autoformat and check bibliography.')
    subparsers = parser.add_subparsers(
        metavar='command',
        dest='command',
        help='available subcommands',
        required=True)
    subparsers.add_parser(
        'check',
        help='check whether bibliography is correctly formatted')
    subparsers.add_parser(
        'format',
        help='format the bibliography')
    subparsers.add_parser(
        'entries',
        help='format entries in the bibliography')
    subparsers.add_parser(
        'clean',
        help='removes entries with invalid IDs')
    subparsers.add_parser(
        'data',
        help='prints data from entries that would be modified')

    argcomplete.autocomplete(parser)
    res = parser.parse_args()
    
    if res.command == "format":
        format_bib('krr2.bib')
        # format_bib('procs.bib')
        return 0

if __name__ == "__main__":
    sys.exit(run())
