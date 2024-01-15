if __name__ == "__main__":
    import argparse, argcomplete

    parser = argparse.ArgumentParser(
            prog='bibfmt',
            description='Autoformat and check bibliography.')
    subparsers = parser.add_subparsers(
        metavar='command',
        dest='command',
        help='available subcommands',
        required=True)
    subparsers.add_parser(
        'search',
        help='searchs entries in dblp')
    subparsers.add_parser(
        'match',
        help='searchs entries in dblp')

    argcomplete.autocomplete(parser)
    args = parser.parse_args()

###############################################################################
###############################################################################
###############################################################################

import os
import time
import datetime
import re
import requests
import bibtexparser as bp
from pprint import pprint
from pathlib import Path
import json

from bibfmt import NON_ALPHANUMERIC_WITH_SPACES_AND_DASHES_RE, NON_ALPHANUMERIC_RE, ID_RE, _parser, _writer, format_names, splitname

DBLP_API_URL = "https://dblp.org/search/publ/api"

def find_dblp_entry(entry, num_results=10):
    
    if "title" not in entry or "year" not in entry:
        return []

    # Construct the query parameters
    entry_title = NON_ALPHANUMERIC_WITH_SPACES_AND_DASHES_RE.sub("", entry["title"].lower())
    # f'title:"{title}" AND author: {authors} AND year:{year}',
    print(entry['ID'])
    query_params = {
        'q': f'{entry_title} {entry["year"]}',
        'format': 'bib',
        'h': num_results,  # Specify the number of results to retrieve
    }
    print(query_params)

    # Make the API request
    response = requests.get(DBLP_API_URL, params=query_params)

    # Check if the request was successful (status code 200)
    while response.status_code == 429:
        raise Exception(f'Error: {response.status_code} {response.reason}', int(response.headers["Retry-After"]))
    if response.status_code != 200:
        raise Exception(f'Error: {response.status_code} {response.reason}')
    dblp_bd = bp.loads(response.text)

    for i, dblp_entry in enumerate(dblp_bd.entries):
        dblp_entry['ID'] = f'{entry["ID"]}${i}${dblp_entry["ID"]}'

    return dblp_bd.entries


def dblp_search_entries(entries, path_write):
    if os.path.exists(path_write):
        with open(path_write, "r") as f:
            in_new = f.read()
        new_db = bp.loads(in_new, _parser())
        skip_entries = set(e['ID'].split("$")[0] for e in new_db.entries)
    else:
        new_db = bp.bibdatabase.BibDatabase()
        skip_entries = None

    no_matches_path = Path(path_write)
    no_matches_path = Path(no_matches_path.parent, no_matches_path.stem + ".no-matches.json")

    if no_matches_path.exists():
        with open(no_matches_path, "r") as f:
            no_matches = json.load(f)
        skip_entries.update(no_matches)
    else:
        no_matches = []

    for entry in entries:
        if skip_entries is not None and entry['ID'] in skip_entries:
            continue
        fast_retry = True
        for _ in range(1, 10):
            success = True
            try:
                new_entries = find_dblp_entry(entry)
                if new_entries:
                    new_db.entries.extend(new_entries)
                else:
                    no_matches.append(entry['ID'])
            except Exception as e:
                success = False
                with open(path_write, "w") as f:
                    bp.dump(new_db, f, _writer())
                with open(no_matches_path, "w") as f:
                    json.dump(no_matches, f)
                if e.args[0].startswith("Error: 429"):
                    if fast_retry:
                        timeout = 60
                        fast_retry = False
                    else:
                        timeout = e.args[1]
                    now_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    print(f"--- Rate limited at {now_time}. Retrying in {timeout} seconds...")
                    time.sleep(timeout)
                else:
                    raise e
            if success:
                break
        
    with open(path_write, "w") as f:
        bp.dump(new_db, f, _writer())

def merge_cross_references(bib_database, procs):
    entries_to_remove = []

    for entry in bib_database.entries:
        # Check if the entry has a 'crossref' field
        if 'crossref' in entry:
            crossref_key = entry['crossref']

            # Find the referenced entry
            referenced_entry = next((e for e in procs.entries if e['ID'] == crossref_key), None)

            # If the referenced entry is found, merge the fields
            if referenced_entry:
                referenced_entry = referenced_entry.copy()
                referenced_entry.pop('ID', None)
                if 'title' in referenced_entry and 'booktitle' not in referenced_entry:
                    referenced_entry['booktitle'] = referenced_entry['title']
                referenced_entry.pop('title', None)
                entry.update(referenced_entry)

                # Add the referenced entry's key to the list of entries to remove
                entries_to_remove.append(crossref_key)


def dblp_search_bibfile(path_read, path_write, path_procs=None):
    with open(path_read, "r") as f:
        in_ = f.read()

    db = bp.loads(in_, _parser())

    if path_procs is not None:
        with open(path_procs, "r") as f:
            in_procs = f.read()
        procs = bp.loads(in_procs, _parser())
        merge_cross_references(db, procs)

    dblp_search_entries(db.entries, path_write)


def split_authors(authors):
    return [ a.strip() for a in authors.replace("\n", " ").split(" and ") ]


def alpha_numeric_lower(s):
    return NON_ALPHANUMERIC_RE.sub("", s.lower())


def match_entries(db, dblp_db):
    mapping = {}
    matches = {}
    for entry in db.entries:
        if 'ID' in entry:
            mapping[entry['ID']] = []
    
    for entry in dblp_db.entries:
        if 'ID' in entry:
            mapping[entry['ID'].split("$")[0]].append(entry)

    for id, dblp_entries in mapping.items():
        entry = db.entries_dict[id]
        if "editor" not in entry or "crossref" not in entry:
            continue
        title = entry["title"]
        crossref_match = ID_RE.match(entry["crossref"])
        if crossref_match is None:
            continue
        crossref_id = crossref_match.group(1)
        authors = split_authors(entry['author'])
        simplified_authors = [alpha_numeric_lower(format_names(a)[0]) for a in authors]
        for dblp_entry in dblp_entries:
            if "ENTRYTYPE" not in dblp_entry or dblp_entry["ENTRYTYPE"] != "inproceedings":
                continue
            if alpha_numeric_lower(title) != alpha_numeric_lower(dblp_entry["title"]):
                continue
            dblp_conference_id = dblp_entry["ID"].split("$")[2].split("/")[1]
            # print(crossref_id, dblp_conference_id)
            if crossref_id != dblp_conference_id:
                continue
            dblp_authors = split_authors(dblp_entry['author'])
            dblp_simplified_authors = [alpha_numeric_lower(format_names(a)[0]) for a in dblp_authors]
            if simplified_authors != dblp_simplified_authors:
                continue
            if id not in matches:
                matches[id] = []
            matches[id].append(dblp_entry["ID"])

    to_remove = []
    for id, dblp_entries in matches.items():
        if len(dblp_entries) == 1:
            continue
        if len(dblp_entries) > 1:
            print(f"Multiple matches for {id}: {dblp_entries}")
        to_remove.append(id)
    
    for id in to_remove:
        matches.pop(id)

    return matches


def format_name(name):
    '''
    Format the given string containing people names.
    '''
    splitted_name = splitname(name)
    if "first" in splitted_name and splitted_name["first"]:
        splitted_name["first"] = [f'{splitted_name["first"][0][0]}.']
    for k, v in list(splitted_name.items()):
        splitted_name[k] = [alpha_numeric_lower(n) for n in v]
    return splitted_name


def eq_formated_names(name1, name2):
    name1f = format_name(name1)
    name2f = format_name(name2)
    return name1f == name2f


def similar_names(name1, name2):
    name1f = format_name(name1)
    name2f = format_name(name2)
    if name1f == name2f:
        return True
    if "first" in name1f and "first" in name2f and name1f["first"] != name2f["first"]:
        return False
    l1 = len(name1f["last"])
    l2 = len(name2f["last"])
    short_last = name1f["last"] if l1 < l2 else name2f["last"]
    long_last = name1f["last"] if l1 >= l2 else name2f["last"]
    return short_last == long_last[-len(short_last):]


def match_editors(db, dblp_db, matches):
    editors_exact_matches = {}
    editors_similar_matches = {}
    for id, dblp_entries in matches.items():
        assert len(dblp_entries) == 1
        entry = db.entries_dict[id]
        dblp_entry = dblp_db.entries_dict[dblp_entries[0]]
        if "editor" not in entry or "editor" not in dblp_entry:
            continue
        editors = split_authors(entry['editor'])
        dblp_editors = split_authors(dblp_entry['editor'])
        if len(editors) != len(dblp_editors):
            continue
        if not all(similar_names(a, b) for a, b in zip(editors, dblp_editors)):
            continue
        for editor, dblp_editor in zip(editors, dblp_editors):
            if eq_formated_names(editor, dblp_editor):
                # if dblp_editor not in editors_exact_matches:
                #     editors_exact_matches[dblp_editor] = dict()
                # editors_exact_matches[dblp_editor][editor] = editors_exact_matches[dblp_editor].get(editor, 0) + 1
                continue
            if similar_names(editor, dblp_editor):
                if dblp_editor not in editors_similar_matches:
                    editors_similar_matches[dblp_editor] = dict()
                editors_similar_matches[dblp_editor][editor] = editors_similar_matches[dblp_editor].get(editor, 0) + 1

    pprint(editors_exact_matches)
    pprint(editors_similar_matches)

def run_match(path_read, path_write, path_procs=None):
        with open("krr.bib", "r") as f:
            in_ = f.read()
        db = bp.loads(in_, _parser())
        with open("dblp1.bib", "r") as f:
            in_ = f.read()
        dblp_db = bp.loads(in_, _parser())
        with open("procs.bib", "r") as f:
            in_ = f.read()
        procs = bp.loads(in_, _parser())
        merge_cross_references(db, procs)
        matched_entries = match_entries(db, dblp_db)
        match_editors(db, dblp_db, matched_entries)
        return 0

def main():
    if args.command == "search":
        dblp_search_bibfile("krr.bib", "dblp1.bib", "procs.bib")
        return 0
    if args.command == "match":
        run_match("krr.bib", "dblp1.bib", "procs.bib")
        return 0

if __name__ == "__main__":
    main()