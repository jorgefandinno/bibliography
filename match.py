import re
import bibtexparser as bp
from bibtexparser.bibdatabase import BibDataStringExpression, as_text
from splitnames import splitname
from authfmt import format_name_dict, split_names_to_strs, CONFIG
from bibfmt import _parser

from pprint import pprint

RE_NON_ALPHANUMERIC = re.compile(r"[^0-9a-zA-Z]+")
RE_NON_ALPHANUMERIC_WITH_SPACES_AND_DASHES = re.compile(r"[^ 0-9a-zA-Z-]+")
RE_NUMERIC = re.compile(r"[0-9]+")
RE_ID = re.compile(r"([a-zA-Z]+)([0-9]+)([a-zA-Z]+)?")

def alpha_numeric_lower(s):
    return RE_NON_ALPHANUMERIC.sub("", s.lower())

def compute_raw_matches(db, dblp_db):
    matches = {}
    for entry in db.entries:
        if 'ID' in entry:
            matches[entry['ID']] = []
    for entry in dblp_db.entries:
        if 'ID' in entry:
            matches[entry['ID'].split("$")[0]].append(entry["ID"])
    return matches

def name_dict_similar(name1, name2):
    if "first" in name1 and "first" in name2 and name1["first"] != name2["first"]:
        return False
    l1 = len(name1["last"])
    l2 = len(name2["last"])
    short_last = name1["last"] if l1 < l2 else name2["last"]
    long_last  = name1["last"] if l1 >= l2 else name2["last"]
    return short_last == long_last[-len(short_last):]

def split_names_to_dicts(names: str) -> list[dict]:
    '''
    Split the given string containing people names into a list of dictionaries representing the name of each person.
    '''
    return [splitname(name) for name in split_names_to_strs(names)]

CONFIG_CONF_MAPPING = CONFIG["conf_mapping"]
CONFIG_JOURNAL_BIB_STRING_MAPPING = CONFIG["journal_bib_string_mapping"]

def similar_venue(entry, dblp_entry):
    """
    Check if the two entries have similar venue.
    """
    venue_type = entry["ENTRYTYPE"]
    if venue_type not in ("inproceedings", "article"):
        return False
    if "ID" not in dblp_entry:
        return False
    dblp_id = dblp_entry["ID"].split("$")[2]
    dblp_venue_id = dblp_id.split("/")[1]
    if venue_type == "inproceedings":
        if "crossref" not in entry or not dblp_id.startswith("DBLP:conf/"):
            return False
        re_match = RE_ID.match(entry["crossref"])
        if not re_match:
            return False
        venue_id = re_match.group(1)
        if dblp_id in CONFIG_CONF_MAPPING:
            dblp_venue_id = CONFIG_CONF_MAPPING[dblp_venue_id]
            return venue_id.lower() == dblp_venue_id.lower()
    if venue_type == "article":
        if "journal" not in entry or not dblp_id.startswith("DBLP:journals/"):
            return False
        journal = entry["journal"]
        if dblp_venue_id in CONFIG_JOURNAL_BIB_STRING_MAPPING:
            print(dblp_venue_id, CONFIG_JOURNAL_BIB_STRING_MAPPING[dblp_venue_id], venue_id)
            return venue_id.lower() == CONFIG_JOURNAL_BIB_STRING_MAPPING[dblp_venue_id]
        if isinstance(journal, BibDataStringExpression) and len(journal.expr) == 1:
            return journal.expr[0].name.lower() == dblp_venue_id.lower()
        if isinstance(journal, str):
            return journal.lower() == dblp_entry["journal"].lower()
    assert False, "Unrecognized venue type""    


def are_similar_entries(entry, dblp_entry, match_venue=True):
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
    if match_venue and not similar_venue(entry, dblp_entry):
        return 0
    if "author" not in entry or "author" not  in dblp_entry:
        return 0
    authors = [format_name_dict(name) for name in split_names_to_dicts(entry["author"])]
    dblp_authors = [format_name_dict(name) for name in split_names_to_dicts(dblp_entry['author'])]
    if len(authors) != len(dblp_authors):
        return 0
    if all(a == b for a, b in zip(authors, dblp_authors)):
        return 2
    return 1 if all(name_dict_similar(a, b) for a, b in zip(authors, dblp_authors)) else 0


def find_similar_entries(db, dblp_db, match_venue=True):
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
            similarity = are_similar_entries(db.entries_dict[id], dblp_db.entries_dict[dblp_id], match_venue=match_venue)
            if similarity == 2:
                similar_entries[id].append(dblp_id)
            elif similarity == 1:
                weakly_similar_entries[id].append(dblp_id)
    similar_entries = {k: v for k, v in similar_entries.items() if v}
    weakly_similar_entries = {k: v for k, v in weakly_similar_entries.items() if v}
    return similar_entries, weakly_similar_entries

with open("krr.bib", "r") as f:
    in_ = f.read()
db = bp.loads(in_, _parser())
with open("dblp1.bib", "r") as f:
    in_ = f.read()
dblp_db = bp.loads(in_, _parser())

similar_entries, weakly_similar_entries = find_similar_entries(db, dblp_db, match_venue=False)

journal_bib_string_mapping = {}
journal_literal_string_mapping = {}

for k, v in similar_entries.items():
    if db.entries_dict[k]["ENTRYTYPE"] != "article" or len(v) != 1:
        continue
    journal = db.entries_dict[k]["journal"]
    dblp_journal = dblp_db.entries_dict[v[0]]["ID"].split("$")[2].split("/")[1]
    if isinstance(journal, BibDataStringExpression) and len(journal.expr) == 1:
        journal_bib_string_mapping[dblp_journal] = journal.expr[0].name
    elif isinstance(journal, str) and journal not in CONFIG_JOURNAL_BIB_STRING_MAPPING:
        dblp_journal = dblp_db.entries_dict[v[0]]["journal"]
        journal_literal_string_mapping[dblp_journal] = journal
    else:
        print("ERROR", journal)

journal_bib_string_mapping = {k: v for k, v in journal_bib_string_mapping.items() if k != v}
journal_literal_string_mapping = {k: v for k, v in journal_literal_string_mapping.items() if k != v}

pprint(journal_bib_string_mapping)
print(80*"=")
pprint(journal_literal_string_mapping)

# pprint(similar_entries)
# print(80*"=")
# pprint(weakly_similar_entries)
# print(80*"=")
# print("Total similar entries:", len(similar_entries))
# print("Total weakly similar entries:", len(weakly_similar_entries))
# print(80*"=")
# print("Multiple matches in similar entries:")
# pprint({k: v for k, v in similar_entries.items() if len(v) > 1})
# print(80*"=")
# print("Multiple matches in weakly similar entries:")
# pprint({k: v for k, v in weakly_similar_entries.items() if len(v) > 1})

similar_entries2, weakly_similar_entries2 = find_similar_entries(db, dblp_db, match_venue=False)

similar_entries2 = {k: v for k, v in similar_entries2.items() if k not in similar_entries and k not in weakly_similar_entries}
weakly_similar_entries2 = {k: v for k, v in weakly_similar_entries2.items() if k not in similar_entries and k not in weakly_similar_entries}

# similar_entries2 = {k: v for k, v in similar_entries2.items() if db.entries_dict[k]["ENTRYTYPE"] == "inproceedings" and "crossref" in db.entries_dict[k]}
# weakly_similar_entries2 = {k: v for k, v in weakly_similar_entries2.items() if db.entries_dict[k]["ENTRYTYPE"] == "inproceedings" and "crossref" in db.entries_dict[k]}

similar_entries2 = {k: v for k, v in similar_entries2.items() if db.entries_dict[k]["ENTRYTYPE"] == "article"}
weakly_similar_entries2 = {k: v for k, v in weakly_similar_entries2.items() if db.entries_dict[k]["ENTRYTYPE"] == "article"}

# print(80*"=")
# pprint(similar_entries2)
# print(80*"=")
# pprint(weakly_similar_entries2)




# print("Total similar entries:", len(similar_entries2))
# print("Total weakly similar entries:", len(weakly_similar_entries2))
# print(80*"=")
# print("Multiple matches in similar entries:")
# pprint({k: v for k, v in similar_entries2.items() if len(v) > 1})
# print(80*"=")
# print("Multiple matches in weakly similar entries:")
# pprint({k: v for k, v in weakly_similar_entries2.items() if len(v) > 1})

