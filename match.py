import re
import json
import bibtexparser as bp
from bibtexparser.bibdatabase import BibDataStringExpression, as_text
from splitnames import splitname
from authfmt import format_name, format_name_dict, split_names_to_strs, CONFIG
from bibfmt import _parser


from pprint import pprint

RE_NON_ALPHANUMERIC = re.compile(r"[^0-9a-zA-Z]+")
RE_NON_ALPHANUMERIC_WITH_SPACES_AND_DASHES = re.compile(r"[^ 0-9a-zA-Z-]+")
RE_NUMERIC = re.compile(r"[0-9]+")
RE_ID = re.compile(r"([a-zA-Z]+)([0-9]+)([a-zA-Z]+)?")

def alpha_numeric_lower_with_spaces(s):
    if isinstance(s, str):
        return RE_NON_ALPHANUMERIC_WITH_SPACES_AND_DASHES.sub("", s.lower())
    if isinstance(s, list):
        return [alpha_numeric_lower_with_spaces(v) for v in s]
    if isinstance(s, dict):
        return { k: alpha_numeric_lower_with_spaces(v) for k, v in s.items() }
    assert False, "Unrecognized type: " + str(type(s)) + " in " + str(s)
     
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
    last1 = [RE_NON_ALPHANUMERIC_WITH_SPACES_AND_DASHES.sub("", pw.lower()) for pw in name1["last"]]
    last2 = [RE_NON_ALPHANUMERIC_WITH_SPACES_AND_DASHES.sub("", pw.lower()) for pw in name2["last"]]
    last1 = [w for pw in last1 for w in pw.split() if w]
    last2 = [w for pw in last2 for w in pw.split() if w]
    l1 = len(last1)
    l2 = len(last2)
    short_last = last1 if l1 < l2 else last2
    long_last  = last1 if l1 >= l2 else last2
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
            # print("NO CROSSREF", entry["ID"])
            return False
        re_match = RE_ID.match(entry["crossref"])
        if not re_match:
            # print("NO MATCH", entry["ID"])
            return False
        # print("NO ISSUE", entry["ID"])
        venue_id = re_match.group(1)
        if dblp_id in CONFIG_CONF_MAPPING:
            # print("IN CONFIG", dblp_venue_id, CONFIG_CONF_MAPPING[dblp_venue_id], venue_id)
            dblp_venue_id = CONFIG_CONF_MAPPING[dblp_venue_id]
        return venue_id.lower() == dblp_venue_id.lower()
    if venue_type == "article":
        return False
        # if "journal" not in entry or not dblp_id.startswith("DBLP:journals/"):
        #     return False
        # journal = entry["journal"]
        # print(dblp_venue_id, dblp_entry["journal"], dblp_entry["ID"])
        # if dblp_venue_id in CONFIG_JOURNAL_BIB_STRING_MAPPING:
        #     return venue_id.lower() == CONFIG_JOURNAL_BIB_STRING_MAPPING[dblp_venue_id]
        # if isinstance(journal, BibDataStringExpression) and len(journal.expr) == 1:
        #     return journal.expr[0].name.lower() == dblp_venue_id.lower()
        # if isinstance(journal, str):
        #     return journal.lower() == dblp_entry["journal"].lower()
    assert False, "Unrecognized venue type: " + venue_type + " in " + str(entry)


def are_similar_entries(entry, dblp_entry, name_mapping=None, match_venue=True):
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
    if name_mapping is None:
        name_mapping = {}
    author_strs = split_names_to_strs(entry["author"])
    dblp_author_strs = split_names_to_strs(dblp_entry['author'])
    if len(author_strs) != len(dblp_author_strs):
        return 0
    authors = [format_name_dict(splitname(name)) for name in author_strs]
    dblp_authors = [format_name_dict(splitname(name)) for name in dblp_author_strs]
    # print(name_mapping)
    for a, b, c, d in zip(authors, dblp_authors, author_strs, dblp_author_strs):
        if a == b:
            continue
        if d in name_mapping and c in name_mapping[d]:
            # print("MATCH", c, " ## ", d, " ## ", name_mapping[d])
            continue
        # print("NO MATCH", c, " ## ", d, " ## ", name_mapping.get(d, None))
    if all(alpha_numeric_lower_with_spaces(a) == alpha_numeric_lower_with_spaces(b) or (d in name_mapping and c in name_mapping[d])  for a, b, c, d in zip(authors, dblp_authors, author_strs, dblp_author_strs)):
        return 2
    return 1 if all(name_dict_similar(a, b) for a, b in zip(authors, dblp_authors)) else 0


def find_similar_entries(db, dblp_db, exclude_ids=None, name_mapping=None, match_venue=True):
    """
    Find similar entries in the dblp database.
    """
    raw_matches = compute_raw_matches(db, dblp_db)
    similar_entries = {}
    weakly_similar_entries = {}
    for id, dblp_ids in raw_matches.items():
        if exclude_ids and id in exclude_ids:
            continue
        similar_entries[id] = []
        weakly_similar_entries[id] = []
        for dblp_id in dblp_ids:
            similarity = are_similar_entries(db.entries_dict[id], dblp_db.entries_dict[dblp_id], name_mapping, match_venue)
            if similarity == 2:
                similar_entries[id].append(dblp_id)
            elif similarity == 1:
                weakly_similar_entries[id].append(dblp_id)
    similar_entries = {k: v for k, v in similar_entries.items() if v}
    weakly_similar_entries = {k: v for k, v in weakly_similar_entries.items() if v}
    return similar_entries, weakly_similar_entries

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



def find_similar_editors_inproceedings(db, dblp_db, exclude_ids, name_mapping, match_venue=True):
    """
    Find similar entries in the dblp database.
    """
    similar_entries, weakly_similar_entries = find_similar_entries(db, dblp_db, exclude_ids, name_mapping, match_venue)

    similar_entries = {k: v for k, v in similar_entries.items() if len(v) == 1}

    editor_name_matches = {}
    editor_name_missmatches = {}

    for id, dblp_entries in similar_entries.items():
        entry = db.entries_dict[id]
        dblp_entry = dblp_db.entries_dict[dblp_entries[0]]
        if "editor" not in entry or "editor" not in dblp_entry:
            continue
        editors = split_names_to_strs(entry["editor"])
        dblp_editors = split_names_to_strs(dblp_entry['editor'])
        if len(editors) != len(dblp_editors):
            continue
        for name, dblp_name in zip(editors, dblp_editors):
            if name_dict_similar(format_name_dict(splitname(name)), format_name_dict(splitname(dblp_name))):
                if dblp_name not in editor_name_matches:
                    editor_name_matches[dblp_name] = set()
                editor_name_matches[dblp_name].add(name)
            else:
                if dblp_name not in editor_name_missmatches:
                    editor_name_missmatches[dblp_name] = set()
                editor_name_missmatches[dblp_name].add(name)

    return similar_entries, weakly_similar_entries, editor_name_matches, editor_name_missmatches


def split_name_for_special_name_config(dblp_name, db_name):
    dblp_name = [w.strip() for w in dblp_name.split()]
    db_name = [w.strip() for w in db_name.split()]
    assert len(dblp_name) >= len(db_name)
    split_position = len(dblp_name) - len(db_name) + 1
    return " ".join(dblp_name[:split_position] + ["|"] + dblp_name[split_position:])

with open("krr.bib", "r") as f:
    in_ = f.read()
db = bp.loads(in_, _parser())
with open("procs.bib", "r") as f:
    in_ = f.read()
procs = bp.loads(in_, _parser())
# merge_cross_references(db, procs)
with open("dblp1.bib", "r") as f:
    in_ = f.read()
dblp_db = bp.loads(in_, _parser())
exclude_ids = set(entry["ID"] for entry in db.entries if "ENTRYTYPE" not in entry or entry["ENTRYTYPE"] != "inproceedings" or "ID" not in entry)
name_mapping = {}
editor_name_missmatches = {}
similar_entries = {}
new = True
while new:
    new = False
    new_similar_entries, weakly_similar_entries, new_editor_name_matches, new_editor_name_missmatches = find_similar_editors_inproceedings(db, dblp_db, exclude_ids, name_mapping, match_venue=False)
    exclude_ids.update(new_similar_entries.keys())
    really_new_editor_name_matches = { k: v for k, v in new_editor_name_matches.items() if k not in name_mapping or v != name_mapping[k] }
    for k, v in really_new_editor_name_matches.items():
        v.difference_update([e for e in v if alpha_numeric_lower_with_spaces(e) == alpha_numeric_lower_with_spaces(format_name(k))])
    really_new_editor_name_matches = { k: v for k, v in really_new_editor_name_matches.items() if v }
    # print(80*"=")
    # pprint(really_new_editor_name_matches)
    # print(80*"=")
    # pprint(new_similar_entries)
    for k, v in really_new_editor_name_matches.items():
        if k not in name_mapping:
            name_mapping[k] = set()
        for name in v:
            if name not in name_mapping[k]:
                new = True
                name_mapping[k].add(name)

special_names = {}
for k, v in name_mapping.items():
    print(k, v)
    v2 = { split_name_for_special_name_config(k, name) for name in v}
    if len(v2) == 1:
        special_names[k] = v2.pop()
    else:
        print("ERROR", k, v2)

print(json.dumps(special_names, indent=4))


# editor_name_with_multiple_matches = {k: v for k, v in new_editor_name_matches.items() if len(v) > 1}

# print(80*"=")
# pprint(new_editor_name_matches)
# print(80*"=")
# pprint(editor_name_with_multiple_matches)
# print(80*"=")
# pprint(new_editor_name_missmatches)

# journal_bib_string_mapping = {}
# journal_literal_string_mapping = {}

# for k, v in similar_entries.items():
#     if db.entries_dict[k]["ENTRYTYPE"] != "article" or len(v) != 1:
#         continue
#     journal = db.entries_dict[k]["journal"]
#     dblp_journal = dblp_db.entries_dict[v[0]]["ID"].split("$")[2].split("/")[1]
#     if isinstance(journal, BibDataStringExpression) and len(journal.expr) == 1:
#         if dblp_journal not in CONFIG_JOURNAL_BIB_STRING_MAPPING or journal.expr[0].name != CONFIG_JOURNAL_BIB_STRING_MAPPING[dblp_journal]:
#             journal_bib_string_mapping[dblp_journal] = journal.expr[0].name
#     elif isinstance(journal, str) and journal not in CONFIG_JOURNAL_BIB_STRING_MAPPING:
#         dblp_journal = dblp_db.entries_dict[v[0]]["journal"]
#         journal_literal_string_mapping[dblp_journal] = journal
#     else:
#         print("ERROR", journal)

# journal_bib_string_mapping = {k: v for k, v in journal_bib_string_mapping.items() if k != v}
# journal_literal_string_mapping = {k: v for k, v in journal_literal_string_mapping.items() if k != v}

# pprint(journal_bib_string_mapping)
# # print(80*"=")
# # pprint(journal_literal_string_mapping)

# # pprint(similar_entries)
# # print(80*"=")
# # pprint(weakly_similar_entries)
# # print(80*"=")
# # print("Total similar entries:", len(similar_entries))
# # print("Total weakly similar entries:", len(weakly_similar_entries))
# # print(80*"=")
# # print("Multiple matches in similar entries:")
# # pprint({k: v for k, v in similar_entries.items() if len(v) > 1})
# # print(80*"=")
# # print("Multiple matches in weakly similar entries:")
# # pprint({k: v for k, v in weakly_similar_entries.items() if len(v) > 1})

# similar_entries2, weakly_similar_entries2 = find_similar_entries(db, dblp_db, match_venue=False)

# similar_entries2 = {k: v for k, v in similar_entries2.items() if k not in similar_entries and k not in weakly_similar_entries}
# weakly_similar_entries2 = {k: v for k, v in weakly_similar_entries2.items() if k not in similar_entries and k not in weakly_similar_entries}

# # similar_entries2 = {k: v for k, v in similar_entries2.items() if db.entries_dict[k]["ENTRYTYPE"] == "inproceedings" and "crossref" in db.entries_dict[k]}
# # weakly_similar_entries2 = {k: v for k, v in weakly_similar_entries2.items() if db.entries_dict[k]["ENTRYTYPE"] == "inproceedings" and "crossref" in db.entries_dict[k]}

# similar_entries2 = {k: v for k, v in similar_entries2.items() if db.entries_dict[k]["ENTRYTYPE"] == "article"}
# weakly_similar_entries2 = {k: v for k, v in weakly_similar_entries2.items() if db.entries_dict[k]["ENTRYTYPE"] == "article"}

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

