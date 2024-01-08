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

import data

NON_ALPHANUMERIC_RE = re.compile(r"[^0-9a-zA-Z]+")
NON_ALPHANUMERIC_WITH_SPACES_AND_DASHES_RE = re.compile(r"[^ 0-9a-zA-Z-]+")
NUMERIC_RE = re.compile(r"[0-9]+")
ID_RE = re.compile(r"([a-zA-Z]+)([0-9]+)([a-zA-Z]+)?")

FIELDS_TO_REMOVE = [
    "bibsource",
    "biburl",
    # "doi",
    "timestamp",
    # "url",
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

def _parser():
    '''
    Return a configured bibtex parser.
    '''
    parser = BibTexParser()
    parser.interpolate_strings = False
    parser.customization = cleanup_record
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

def _fixdb(db):
    '''
    Currently sorts the strings in the database.
    '''
    db.strings = OrderedDict(sorted(db.strings.items()))
    return db

def format_bib(path):
    '''
    Format the given bibliography file.
    '''
    # read bibliography
    with open(path, "r") as f:
        db = _fixdb(bp.load(f, _parser()))

    # write the bibliography
    with open(path, "w") as f:
        bp.dump(db, f, _writer())

def check_bib(path):
    '''
    Check if the given bibliography is correctly formatted.
    '''
    # read bibliography
    with open(path, "r") as f:
        in_ = f.read()

    db = _fixdb(bp.loads(in_, _parser()))

    # write the bibliography
    out = StringIO()
    bp.dump(db, out, _writer())

    return [x for x in ndiff(in_.splitlines(), out.getvalue().splitlines()) if x[0] != ' ']

def splitname(name, strict_mode=True):
    """
    Break a name into its constituent parts: First, von, Last, and Jr.

    :param string name: a string containing a single name
    :param Boolean strict_mode: whether to use strict mode
    :returns: dictionary of constituent parts
    :raises `customization.InvalidName`: If an invalid name is given and
                                         ``strict_mode = True``.

    In BibTeX, a name can be represented in any of three forms:
        * First von Last
        * von Last, First
        * von Last, Jr, First

    This function attempts to split a given name into its four parts. The
    returned dictionary has keys of ``first``, ``last``, ``von`` and ``jr``.
    Each value is a list of the words making up that part; this may be an empty
    list.  If the input has no non-whitespace characters, a blank dictionary is
    returned.

    It is capable of detecting some errors with the input name. If the
    ``strict_mode`` parameter is ``True``, which is the default, this results in
    a :class:`customization.InvalidName` exception being raised. If it is
    ``False``, the function continues, working around the error as best it can.
    The errors that can be detected are listed below along with the handling
    for non-strict mode:

        * Name finishes with a trailing comma: delete the comma
        * Too many parts (e.g., von Last, Jr, First, Error): merge extra parts
          into Last. The second part is merged into First if it is an initial.
        * Unterminated opening brace: add closing brace to end of input
        * Unmatched closing brace: add opening brace at start of word

    """
    # Modified from the bibtexparser.customization.splitname function to merge into Last instead of First.
    # The ``von`` part is ignored unless commans are used as separators. Note that ``von`` part colides with uncapitalized parts of the last name.
    # Useful references:
    # http://maverick.inria.fr/~Xavier.Decoret/resources/xdkbibtex/bibtex_summary.html#names
    # http://tug.ctan.org/info/bibtex/tamethebeast/ttb_en.pdf

    # Group names of exceptional cases.
    if " ".join(name.split()) in data.GROUPING_NAMES:
        name_t = data.GROUPING_NAMES[name]
        return {'first': [name_t[0]], 'von': [name_t[1]], 'last': [name_t[2]], 'jr': [name_t[3]]} 

    # Whitespace characters that can separate words.
    whitespace = set(' ~\r\n\t')

    # We'll iterate over the input once, dividing it into a list of words for
    # each comma-separated section. We'll also calculate the case of each word
    # as we work.
    sections = [[]]  # Sections of the name.
    cases = [[]]  # 1 = uppercase, 0 = lowercase, -1 = caseless.
    word = []  # Current word.
    case = -1  # Case of the current word.
    level = 0  # Current brace level.
    bracestart = False  # Will the next character be the first within a brace?
    controlseq = True  # Are we currently processing a control sequence?
    specialchar = None  # Are we currently processing a special character?

    # Using an iterator allows us to deal with escapes in a simple manner.
    nameiter = iter(name)
    for char in nameiter:
        # An escape.
        if char == '\\':
            escaped = next(nameiter)

            # BibTeX doesn't allow whitespace escaping. Copy the slash and fall
            # through to the normal case to handle the whitespace.
            if escaped in whitespace:
                word.append(char)
                char = escaped
            else:
                # Is this the first character in a brace?
                if bracestart:
                    bracestart = False
                    controlseq = escaped.isalpha()
                    specialchar = True

                # Can we use it to determine the case?
                elif (case == -1) and escaped.isalpha():
                    if escaped.isupper():
                        case = 1
                    else:
                        case = 0

                # Copy the escape to the current word and go to the next
                # character in the input.
                word.append(char)
                word.append(escaped)
                continue

        # Start of a braced expression.
        if char == '{':
            level += 1
            word.append(char)
            bracestart = True
            controlseq = False
            specialchar = False
            continue

        # All the below cases imply this (and don't test its previous value).
        bracestart = False

        # End of a braced expression.
        if char == '}':
            # Check and reduce the level.
            if level:
                level -= 1
            else:
                if strict_mode:
                    raise bp.customization.InvalidName("Unmatched closing brace in name {{{0}}}.".format(name))
                word.insert(0, '{')

            # Update the state, append the character, and move on.
            controlseq = False
            specialchar = False
            word.append(char)
            continue

        # Inside a braced expression.
        if level:
            # Is this the end of a control sequence?
            if controlseq:
                if not char.isalpha():
                    controlseq = False

            # If it's a special character, can we use it for a case?
            elif specialchar:
                if (case == -1) and char.isalpha():
                    if char.isupper():
                        case = 1
                    else:
                        case = 0

            # Append the character and move on.
            word.append(char)
            continue

        # End of a word.
        # NB. we know we're not in a brace here due to the previous case.
        if char == ',' or char in whitespace:
            # Don't add empty words due to repeated whitespace.
            if word:
                sections[-1].append(''.join(word))
                word = []
                cases[-1].append(case)
                case = -1
                controlseq = False
                specialchar = False

            # End of a section.
            if char == ',':
                if len(sections) < 3:
                    sections.append([])
                    cases.append([])
                elif strict_mode:
                    raise bp.customization.InvalidName("Too many commas in the name {{{0}}}.".format(name))
            continue

        # Regular character.
        word.append(char)
        if (case == -1) and char.isalpha():
            if char.isupper():
                case = 1
            else:
                case = 0

    # Unterminated brace?
    if level:
        if strict_mode:
            raise bp.customization.InvalidName("Unterminated opening brace in the name {{{0}}}.".format(name))
        while level:
            word.append('}')
            level -= 1

    # Handle the final word.
    if word:
        sections[-1].append(''.join(word))
        cases[-1].append(case)

    # Get rid of trailing sections.
    if not sections[-1]:
        # Trailing comma?
        if (len(sections) > 1) and strict_mode:
            raise bp.customization.InvalidName("Trailing comma at end of name {{{0}}}.".format(name))
        sections.pop(-1)
        cases.pop(-1)

    # No non-whitespace input.
    if not sections or not any(bool(section) for section in sections):
        return {}

    # Initialise the output dictionary.
    parts = {'first': [], 'last': [], 'von': [], 'jr': []}

    # Form 1: "First von Last"
    # print(f"{sections=}")
    # print(cases)
    if len(sections) == 1:
        p0 = sections[0]
        cases = cases[0]
        # One word only: last cannot be empty.
        if len(p0) == 1:
            parts['last'] = p0

        # Two words: must be first and last.
        elif len(p0) == 2:
            parts['first'] = p0[:1]
            parts['last'] = p0[1:]

        # Need to use the cases to figure it out.
        elif len(p0) > 2 and p0[1][1] == ".":
            parts['first'] = p0[:2]
            parts['last'] = p0[2:]
        else:
            num_capitals = sum(cases)
            if num_capitals > 2:
                capital_position = [i for i,e in enumerate(cases) if e]
                third_to_last_captilized = capital_position[-3] + 1
                parts['first'] = p0[:third_to_last_captilized]
                parts['last'] = p0[third_to_last_captilized:]
            else:
                parts['first'] = p0[:1]
                parts['last'] = p0[1:]


    # Form 2 ("von Last, First") or 3 ("von Last, jr, First")
    else:
        # As long as there is content in the first name partition, use it as-is.
        first = sections[-1]
        if first and first[0]:
            parts['first'] = first

        # And again with the jr part.
        if len(sections) == 3:
            jr = sections[-2]
            if jr and jr[0]:
                parts['jr'] = jr

        # Last name cannot be empty; if there is only one word in the first
        # partition, we have to use it for the last name.
        last = sections[0]
        if len(last) == 1:
            parts['last'] = last

        # Have to look at the cases to figure it out.
        else:
            lcases = cases[0]

            # At least one lowercase: von is the longest sequence of whitespace
            # separated words whose last word does not start with an uppercase
            # word, and last is the rest.
            if 0 in lcases:
                split = len(lcases) - lcases[::-1].index(0)
                if split == len(lcases):
                    split = 0  # Last cannot be empty.
                parts['von'] = sections[0][:split]
                parts['last'] = sections[0][split:]

            # All uppercase => all last.
            else:
                parts['last'] = sections[0]

    # Done.
    return parts

def join_names_parts(name_parts: dict) -> dict:
    '''
    Concatenate the name information into a string.
    '''
    d = {}
    d["first"] = " ".join(name_parts.get("first", []))
    d["von"] = " ".join(name_parts.get("von", []))
    d["last"] = " ".join(name_parts.get("last", []))
    d["jr"] = " ".join(name_parts.get("jr", []))
    return d


def name_parts_to_str(name_parts):
    '''
    Concatenate the name information into a string.
    '''
    # print("name_info", name_info)
    first = name_parts["first"]
    von = name_parts["von"]
    last = name_parts["last"]
    jr = name_parts["jr"]
    previous = first != ""
    if previous and von:
        von = f" {von}"
    if previous and last:
        last = f" {last}"
    if previous and jr:
        jr = f" {jr}"
    return f"{first}{von}{last}{jr}"



def format_first_name(name: str) -> str:
    if len(name) > 2 and "{" not in name[:2] and "\\" not in name[:2]:
        name = f"{name[0]}."
    return name



def generate_key_from_surnames(surnames: list[str]) -> str:
    '''
    Generate a key from the given list of surnames.
    '''
    surnames = [NON_ALPHANUMERIC_RE.sub("", x.lower()) for x in surnames if x]
    if not surnames:
        return ""
    if len(surnames) == 1:
        return surnames[0]
    surnames = [x+"___" for x in surnames if x]
    l = 3 if len(surnames) == 2 else 2
    return "".join([y[:l] for y in surnames])

def format_names_and_generate_id(x):
    '''
    Format the given string containing people names.
    '''
    modified_people = set()
    splitted_names = []
    for name in x.replace("\n", " ").split(' and '):
        if name in data.WHOLE_NAMES:
            splitted_names.append({"last": [name]})
            continue
        splitted_name = splitname(name)
        if "first" in splitted_name:
            first_name = " ".join(splitted_name["first"])
            splitted_name_tuple = (first_name, " ".join(splitted_name["von"]), " ".join(splitted_name["last"]), " ".join(splitted_name["jr"]))
            if splitted_name_tuple not in data.SPLITED_NAMES:
                formated_first_name = format_first_name(first_name)
                splitted_name["first"] = [formated_first_name]
                if first_name != formated_first_name:
                    modified_people.add(splitted_name_tuple)
        splitted_names.append(splitted_name)
    splitted_names = [join_names_parts(x) for x in splitted_names]
    formated_names = ' and '.join(name_parts_to_str(splitted_name) for splitted_name in splitted_names)
    surnames = [splitted_name["last"]  for splitted_name in splitted_names]
    return formated_names, modified_people, generate_key_from_surnames(surnames)

def format_names(x: str) -> str:
    '''
    Format the given string containing people names.
    '''
    return format_names_and_generate_id(x)[:2]

def _new_id(id_base, year, existing_ids=set()):
    '''
    Generate a new id.
    '''
    if len(year) > 2:
        year = year[-2:]
    for size in itertools.count(1):
        for suffix in itertools.product(string.ascii_lowercase, repeat=size):
            new_id = id_base + year + "".join(suffix)
            if new_id not in existing_ids:
                return new_id

def _dblp_crossref_to_id(crossref):
    '''
    Convert a DBLP crossref to an id.
    '''
    _, crossref_key, year = crossref.split("/")
    year = year[-2:] if len(year) > 2 else year
    return crossref_key + year

def _format_bib_entry(entry, existing_ids, db, procs_db):
    new_entry = entry.copy()
    for field in FIELDS_TO_REMOVE:
        if field in new_entry:
            new_entry.pop(field)
    if 'author' in new_entry:
        new_entry['author'], modified_authors, base_id = format_names_and_generate_id(new_entry['author'])
        if base_id and "ID" in new_entry and new_entry["ID"].startswith("DBLP:") and "year" in entry:
            new_entry["ID"] = _new_id(base_id, entry["year"], existing_ids)
    else:
        modified_authors = set()
    if 'editor' in entry:
        new_entry['editor'], modified_editors = format_names(new_entry['editor'])
    else:
        modified_editors = set()
    if "journal" in entry and isinstance(entry["journal"], str) and entry["journal"] in data.JOURNAL_MAPPING:
        bib_string = BibDataStringExpression([BibDataString(db, data.JOURNAL_MAPPING[entry["journal"]])])
        new_entry["journal"] = bib_string
    if procs_db is not None and entry["ENTRYTYPE"].lower() == "inproceedings" and "crossref" in entry and entry["crossref"].startswith("DBLP:"):
        crossref = _dblp_crossref_to_id(entry["crossref"])
        if crossref in procs_db.entries_dict:
            new_entry["crossref"] = crossref
            new_entry.pop("booktitle", None)
            new_entry.pop("year", None)
        

    if new_entry == entry:
        return entry, set()
    return new_entry, modified_authors | modified_editors

def _similar_entries(entry1, entry2):
    title1 = NON_ALPHANUMERIC_RE.sub("", entry1.get("title", "").lower())
    title2 = NON_ALPHANUMERIC_RE.sub("", entry2.get("title", "").lower())
    return title1 == title2


def format_bib_entries(path, *, procs_db=None, return_modified=False):
    '''
    Format the given bibliography file.
    '''
    # read bibliography
    with open(path, "r") as f:
        db = _fixdb(bp.load(f, _parser()))

    existing_ids = set(entry["ID"] for entry in db.entries)
    modified_people = set() if return_modified else None
    modified_ids = set() if return_modified else None

    if procs_db is not None:
        db_dict = {}
        for entry in db.entries:
            id_base = ID_RE.match(entry["ID"])
            if id_base is not None:
                id_base = "".join(id_base.groups()[:2])
                if id_base not in db_dict:
                    db_dict[id_base] = []
                db_dict[id_base].append(entry)

    new_entries = []
    for entry in db.entries:
        if "ID" in entry and entry["ID"] in data.EXCLUDE_IDS:
            new_entries.append(entry)
            continue
        new_entry, modified_people_here = _format_bib_entry(entry, existing_ids, db, procs_db)
        new_entries.append(new_entry)
        if modified_ids is not None and new_entry is not entry:
            modified_ids.add(entry["ID"])
            if modified_people is not None:
                modified_people |= modified_people_here
        if new_entry is not entry and procs_db is not None:
            id_match = ID_RE.match(new_entry["ID"])
            if id_match is not None:
                id_base = "".join(id_match.groups()[:2])
                if entry["ENTRYTYPE"].lower() != "proceedings" and id_base in db_dict:
                    for db_entry in db_dict[id_base]:
                        if _similar_entries(new_entry, db_entry):
                            db_entry_id = db_entry["ID"]
                            new_entry["ID"] = f"REPEATED:{db_entry_id}"
                            break
                if entry["ENTRYTYPE"].lower() == "proceedings" and new_entry["ID"] in procs_db.entries_dict:
                    print(_dblp_crossref_to_id(entry["ID"]))
            elif entry["ENTRYTYPE"].lower() == "proceedings" and entry["ID"].startswith("DBLP:"):
                procs_db_entry_id = _dblp_crossref_to_id(entry["ID"]) 
                if procs_db_entry_id in procs_db.entries_dict:
                    new_entry["ID"] = f"REPEATED:{procs_db_entry_id}"
        
    db.entries = new_entries

    # write the bibliography
    if not return_modified:
        with open(path, "w") as f:
            bp.dump(db, f, _writer(sorted_entries=False))
        return db
    else:
        return modified_ids, modified_people
    

def clean_bib(path):
    '''
    Format the given bibliography file.
    '''
    # read bibliography
    with open(path, "r") as f:
        db = _fixdb(bp.load(f, _parser()))

    new_entries = []
    for entry in db.entries:
        if not entry["ID"].startswith("REPEATED:") and not entry["ID"].startswith("DBLP:"):
            new_entries.append(entry)

    db.entries = new_entries

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
        format_bib('krr.bib')
        format_bib('procs.bib')
        return 0
    
    if res.command == "entries":
        procs = format_bib_entries('procs.bib')
        format_bib_entries('krr.bib', procs_db=procs)
        # format_bib_entries('jorge.bib', procs_db=procs)
        return 0
    
    if res.command == "clean":
        clean_bib('krr.bib')
        return 0
    
    if res.command == "data":
        modified_ids1, modified_people1 = format_bib_entries('krr.bib', return_modified=True)
        modified_ids2, modified_people2 = format_bib_entries('procs.bib', return_modified=True)
        print("SPLITED_NAMES = {")
        for x in sorted(modified_people1 | modified_people2):
            # print(f"    ({x[0]}, {x[1]}, {x[2]}, {x[3]}),")
            print(f"    {x},")
        print("}\n\n")
        print("EXCLUDE_IDS = {")
        for x in sorted(modified_ids1 | modified_ids2):
            print(f"    '{x}',")
        print("}\n\n")
        return 0

    assert res.command == "check"
    diff = check_bib('krr.bib') + check_bib('procs.bib')
    if diff:
        for x in diff:
            print(x, file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(run())
