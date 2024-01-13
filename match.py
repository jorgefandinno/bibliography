import bibtexparser as bp
from authfmt import format_name_dict, split_names_to_strs
from bibfmt import _parser


RE_NON_ALPHANUMERIC = re.compile(r"[^0-9a-zA-Z]+")
RE_NON_ALPHANUMERIC_WITH_SPACES_AND_DASHES = re.compile(r"[^ 0-9a-zA-Z-]+")
RE_NUMERIC = re.compile(r"[0-9]+")
RE_ID = re.compile(r"([a-zA-Z]+)([0-9]+)([a-zA-Z]+)?")

def alpha_numeric_lower(s):
    return RE_NON_ALPHANUMERIC.sub("", s.lower())

def name_dict_similar(name1, name2):
    if "first" in name1 and "first" in name2 and name1["first"] != name2["first"]:
        return False
    l1 = len(name1["last"])
    l2 = len(name2["last"])
    short_last = name1["last"] if l1 < l2 else name2["last"]
    long_last  = name1["last"] if l1 >= l2 else name2["last"]
    return short_last == long_last[-len(short_last):]

def compute_raw_matches(db, dblp_db):
    matches = {}
    for entry in db.entries:
        if 'ID' in entry:
            matches[entry['ID']] = []
    for entry in dblp_db.entries:
        if 'ID' in entry:
            matches[entry['ID'].split("$")[0]].append(entry)
    return matches

def are_similar_entries(entry, dblp_entry):
    """
    Check if the two entries are  similar.
    It returns a integer: 0 (not similar), 1 (weakly similar) or 2 (similar).
    Two entries are similar if they have the same type, title, year and formated authors.
    Two entries are weakly similar if they have the same type, title, year and similar authors.
    Authors if they agree on their abbreviated first name and the last part of their last name.
    """
    if "ENTRYTYPE" not in entry or "ENTRYTYPE" not in dblp_entry or entry["ENTRYTYPE"] != dblp_entry["ENTRYTYPE"]:
        return 0
    if "title" not in entry or "title" not in dblp_entry:
        return 0
    if alpha_numeric_lower(entry["title"]) != alpha_numeric_lower(dblp_entry["title"]):
        return 0
    if "year" not in entry or "year" not in dblp_entry or entry["year"] != dblp_entry["year"]:
        return 0
    if "author" not in entry or "author" not  in dblp_entry:
        return 0
    authors = format_name_dict(split_names_to_strs(entry["author"]))
    dblp_authors = format_name_dict(split_names_to_strs(dblp_entry['author']))
    if len(authors) != len(dblp_authors):
        return 0
    if all(a == b for a, b in zip(authors, dblp_authors)):
        return 2
    return 1 if all(name_dict_similar(a, b) for a, b in zip(authors, dblp_authors)) else 0


def find_similar_entries(db, dblp_db):
    """
    Find similar entries in the dblp database.
    """
    raw_matches = compute_raw_matches(db, dblp_db)
    similar_entries = {}
    weakly_similar_entries = {}
    for id, dblp_ids in raw_matches.items():
        similar_entries[id] = []
        weakly_similar_entries[id] = []
        for dblp_id in dblp_ids:
            similarity = are_similar_entries(db.entries[id], dblp_db.entries[dblp_id])
            if similarity == 2:
                similar_entries[id].append(dblp_ids)
            elif similarity == 1:
                weakly_similar_entries[id].append(dblp_ids)
    return similar_entries, weakly_similar_entries

with open("krr.bib", "r") as f:
    in_ = f.read()
import bp

db = bp.loads(in_, _parser())
with open("dblp1.bib", "r") as f:
    in_ = f.read()
dblp_db = bp.loads(in_, _parser())

similar_entries, weakly_similar_entries = find_similar_entries(db, dblp_db)

from pprint import pprint
pprint(similar_entries)
print(80*"=")
pprint(weakly_similar_entries)