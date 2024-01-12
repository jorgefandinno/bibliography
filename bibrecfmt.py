#!/usr/bin/env python3
'''
Script using the bibtexparser module to cleanup_record and pretty print our
bibliography.
'''

import sys
from io import StringIO
from argparse import ArgumentParser
from difflib import ndiff
from collections import OrderedDict
import itertools
import string
import requests

import bibtexparser as bp
from bibtexparser.bibdatabase import BibDataStringExpression, BibDataString
from bibtexparser.bparser import BibTexParser
from bibtexparser.bwriter import BibTexWriter
from bibtexparser.latexenc import unicode_to_latex_map

import data
from pprint import pprint
import re


NON_ALPHANUMERIC_RE = re.compile(r"[^0-9a-zA-Z]+")
NON_ALPHANUMERIC_WITH_SPACES_AND_DASHES_RE = re.compile(r"[^ 0-9a-zA-Z-]+")
NUMERIC_RE = re.compile(r"[0-9]+")

modified_people = set()
existing_ids = set()
modified_ids = set()

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
          into Last
        * Unterminated opening brace: add closing brace to end of input
        * Unmatched closing brace: add opening brace at start of word

    """
    # Modified from the bibtexparser.customization.splitname function to merge into Last instead of First.
    # The ``von`` part is ignored unless commans are used as separators. Note that ``von`` part colides with uncapitalized parts of the last name.
    # Useful references:
    # http://maverick.inria.fr/~Xavier.Decoret/resources/xdkbibtex/bibtex_summary.html#names
    # http://tug.ctan.org/info/bibtex/tamethebeast/ttb_en.pdf

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

        # One word only: last cannot be empty.
        if len(p0) == 1:
            parts['last'] = p0

        # Two words: must be first and last.
        elif len(p0) == 2:
            parts['first'] = p0[:1]
            parts['last'] = p0[1:]

        # Need to use the cases to figure it out.
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
    # if "\n" in x:
    #     return x, ""
    splitted_names = []
    for name in x.split(' and '):
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
    return formated_names, generate_key_from_surnames(surnames)

def format_names(x: str) -> str:
    '''
    Format the given string containing people names.
    '''
    return format_names_and_generate_id(x)[0]

def _cleanup_record_other_than_id(x: dict, val: str) -> None:
    x[val] = apply_on_expression(x[val], cleanup_expression)
    if val.lower() == 'pages':
        x[val] = x[val].replace('--', '-')
    if x["ID"] == "baraltt02":
        print(f"{val=} {x[val]=}")
    if val.lower() == 'author':
        x[val], id = format_names_and_generate_id(x[val])
        if id and "ID" in x and x["ID"].startswith("DBLP:"):
            x["ID"] = f"NEWID:{id}"
    if val.lower() == 'editor':
        x[val] = format_names(x[val])


def cleanup_record(x):
    '''
    Cleanup a record as returned by the bibtexparser module.
    '''
    if "ID" in x and x["ID"] in data.EXCLUDE_IDS:
        return x
    y = x.copy()
    for field in FIELDS_TO_REMOVE:
        if field in y:
            y.pop(field)
    for val in y:
        if val == "ID":
            existing_ids.add(y[val])
        else:
            _cleanup_record_other_than_id(y, val)
    if x != y and "ID" in x:
        modified_ids.add(x["ID"])
    return y

def _parser():
    '''
    Return a configured bibtex parser.
    '''
    parser = BibTexParser()
    parser.interpolate_strings = False
    parser.customization = cleanup_record
    return parser

def _writer():
    '''
    Return a configured bibtex writer.
    '''
    writer = BibTexWriter()
    writer.indent = '  '
    writer.order_entries_by = None
    # writer.order_entries_by = ('ID',)
    writer.display_order = ['title', 'author', 'editor']
    return writer

def _new_id(id_base, year):
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

def _fixdb(db):
    '''
    Currently sorts the strings in the database.
    '''
    db.strings = OrderedDict(sorted(db.strings.items()))
    for entry in db.entries:
        if "ID" in entry and entry["ID"].startswith("NEWID:") and "year" in entry:
            entry["ID"] = _new_id(entry["ID"][6:], entry["year"])
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

def format_bib_entries(path):
    '''
    Format the given bibliography file.
    '''
    # read bibliography
    with open(path, "r") as f:
        db = _fixdb(bp.load(f, _parser()))

    for entry in db.entries:
        if "journal" in entry and isinstance(entry["journal"], str) and entry["journal"] in data.JOURNAL_MAPPING:
            bib_string = BibDataString(db, data.JOURNAL_MAPPING[entry["journal"]])
            entry["journal"] = bib_string

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

def store_special_names(path):
    '''
    Format the given bibliography file.
    '''
    # read bibliography
    with open(path, "r") as f:
        db = _fixdb(bp.load(f, _parser()))

def find_dblp_entries(entry, num_results=10):
    # DBLP API base URL
    api_url = "https://dblp.org/search/publ/api"

    # Construct the query parameters
    entry_title = NON_ALPHANUMERIC_WITH_SPACES_AND_DASHES_RE.sub("", entry["title"].lower())
    entry_authors = [ NON_ALPHANUMERIC_RE.sub("",a.lower()) for a in entry["author"].split(" and ") ]
    # f'title:"{title}" AND author: {authors} AND year:{year}',
    query_params = {
        'q': f'{entry_title} {entry["year"]}',
        'format': 'json',
        'h': num_results,  # Specify the number of results to retrieve
    }
    # print(query_params)

    # Make the API request
    response = requests.get(api_url, params=query_params)

    # Check if the request was successful (status code 200)
    if response.status_code != 200:
        raise Exception(f'Error: {response.status_code} {response.reason}')
    # Parse the JSON response
    data = response.json()
    # Check if any results were found
    if 'result' in data and 'hits' in data['result'] and int(data['result']['hits']['@total']) == 0:
        print("NO RESULTS for:", entry_title, entry["year"])
        return None
        # Extract information from each result
    for hit in data['result']['hits']['hit']:
        result_info = hit['info']
        if (
            NON_ALPHANUMERIC_RE.sub("", result_info['title'].lower()) != NON_ALPHANUMERIC_RE.sub("", entry["title"].lower())
            or
            result_info['year'] != entry["year"]
        ):
            print("TITLE:",result_info['title'], entry["title"])
            print("YEAR:",result_info['year'], entry["year"])
            # continue
        key = result_info['key']
        result_bib = requests.get(f'https://dblp.uni-trier.de/rec/bib0/{key}.bib')
        if response.status_code!= 200:
            raise Exception(f'Error: {response.status_code} {response.reason}')
        dblp = bp.loads(result_bib.text)
        authors = [ a.strip() for a in dblp.entries[0]['author'].replace("\n", " ").split(" and ") ]
        if len(authors) != len(entry_authors):
            print("AUTHORS1:", authors, entry_authors)
            # continue  
        formated_authors = [NON_ALPHANUMERIC_RE.sub("",format_names(a).lower()) for a in authors]
        if all(a1 != a2 for a1, a2 in zip(formated_authors, entry_authors)):
            print("AUTHORS2:", formated_authors, entry_authors)
            # continue
        return dblp.entries[0]
    return None


def run_dblp(path):
    with open(path, "r") as f:
        in_ = f.read()

    db = _fixdb(bp.loads(in_, _parser()))

    journals_already_processed = set(data.JOURNAL_MAPPING.values())
    journals_already_processed.update(data.SKIP_JOURNALS)
    article_mapping = {}

    for entry in db.entries:
        if (
            entry['ENTRYTYPE'].lower() == 'article' 
            and "journal" in entry
            and isinstance(entry["journal"], BibDataStringExpression)
            and entry["journal"].expr[0].name not in journals_already_processed
        ):
            print(type(entry["journal"]), entry["journal"])
            try:
                dblp_entry = find_dblp_entries(entry)
            except Exception as e:
                print(e.args)
                break
            if dblp_entry and "journal" in dblp_entry:
                article_mapping[dblp_entry["journal"]] = entry["journal"].expr[0].name
                journals_already_processed.add(entry["journal"].expr[0].name)
    return article_mapping

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
        'data',
        help='generate data from the bibliography')
    subparsers.add_parser(
        'dblp',
        help='format the bibliography')

    res = parser.parse_args()

    if res.command == "format":
        format_bib('krr.bib')
        format_bib('procs.bib')
        return 0

    if res.command == "entries":
        # format_bib('krr.bib')
        # format_bib('procs.bib')
        format_bib_entries('small.bib')
        return 0
    
    if res.command == "data":
        store_special_names('krr.bib')
        store_special_names('procs.bib')
        print("SPLITED_NAMES = {")
        for x in sorted(modified_people):
            # print(f"    ({x[0]}, {x[1]}, {x[2]}, {x[3]}),")
            print(f"    {x},")
        print("}\n\n")
        print("EXCLUDE_IDS = {")
        for x in sorted(modified_ids):
            print(f"    '{x}',")
        print("}\n\n")
        return 0
    
    if res.command == "dblp":
        article_mapping = run_dblp("krr.bib")
        print("ARTICLE_MAPPING = {")
        for k, v in article_mapping.items():
            print(f"    '{k}': '{v}',")
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
